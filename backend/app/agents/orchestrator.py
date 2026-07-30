from __future__ import annotations

import concurrent.futures as _futures

from sqlalchemy.orm import Session

from app.agents.base import AGENT_REGISTRY, Agent
from app.agents.employee_finder import employee_finder_agent
from app.agents.enrichment import enrichment_agent
from app.agents.outreach import nudge_missing_company, outreach_agent
from app.agents.scoring import scoring_agent
from app.agents.tracking import tracking_agent
from app.agents.email_guess_verification import email_guess_verification_agent
from app.core.database import SessionLocal
from app.models import AgentConfig, Campaign, Company, Contact, EmailDraft, User
from app.services import contact_directory
from app.services import snapshots
from app.services.events import add_notification
from app.services.pipeline_locks import is_locked, locked_contact_ids


def ensure_agents(db: Session, owner_id: int) -> None:
    """Create the canonical agent rows for a user if missing, and keep each
    existing row's name/description in sync with the registry (the source of
    truth) so copy changes reach already-seeded users too."""
    rows = {
        a.key: a
        for a in db.query(AgentConfig).filter(AgentConfig.owner_id == owner_id)
    }
    for order, (key, name, desc) in enumerate(AGENT_REGISTRY, start=1):
        cfg = rows.get(key)
        if cfg is None:
            db.add(
                AgentConfig(
                    owner_id=owner_id,
                    key=key,
                    name=name,
                    description=desc,
                    order=order,
                    enabled=True,
                    status="Idle",
                )
            )
        elif cfg.name != name or cfg.description != desc:
            cfg.name = name
            cfg.description = desc
    db.commit()


def _enabled(db: Session, owner_id: int, key: str) -> bool:
    cfg = (
        db.query(AgentConfig)
        .filter(AgentConfig.owner_id == owner_id, AgentConfig.key == key)
        .first()
    )
    return cfg.enabled if cfg else True


def _phase(db: Session, owner_id: int, agent: Agent, fn) -> None:
    if not _enabled(db, owner_id, agent.key):
        return
    agent.mark(db, owner_id, "Running")
    try:
        fn()
        agent.mark(db, owner_id, "Idle")
    except Exception:
        agent.mark(db, owner_id, "Error")
        raise


# Bounded fan-out for enrichment. External rate limits (DuckDuckGo throttling,
# the AI provider's 60s 429 cooldown) dominate over local CPU, so a small pool
# is both faster and safer than unbounded concurrency. Kept well under the DB
# connection-pool ceiling (see core/database.py, which pins pool_size to match).
ENRICH_MAX_WORKERS = 4

# Non-approved (no-access) users get a credit-capped preview: this many companies
# are enriched + scored, and ONE contact (with its email) is found for the top one.
PREVIEW_COMPANIES = 2


def _enrich_one(company_id: int, campaign_id: int, owner_id: int, force_ai: bool) -> None:
    """Enrich a single company on a PRIVATE session — safe inside a worker
    thread. Opens its own SessionLocal(), re-fetches the Company + Campaign by id
    (the orchestrator's ORM objects belong to another thread's session and must
    never be touched here), runs the existing agent, and always closes. Per-
    company exceptions are swallowed + logged so one bad company can't abort the
    batch (mirrors the finder's tolerance in _walk_for_contactable)."""
    db = SessionLocal()
    try:
        company = db.get(Company, company_id)
        campaign = db.get(Campaign, campaign_id)
        if company is not None and campaign is not None:
            enrichment_agent.run(db, company, campaign, owner_id, force_ai=force_ai)
    except Exception:
        try:
            enrichment_agent.log(
                db, owner_id, f"Enrichment failed for company {company_id}.", level="error",
            )
        except Exception:
            pass
    finally:
        db.close()


def _run_enrichment_concurrent(
    companies: list[Company], campaign_id: int, owner_id: int, force_ai: bool,
) -> None:
    """Fan enrichment out across a bounded thread pool, one private session per
    worker. Capture ids up front so no ORM object (bound to THIS thread's
    session) crosses a thread boundary. Blocks until every worker joins, so the
    caller (a _phase lambda) only returns once the whole batch is done — which
    preserves the enrichment → scoring ordering and keeps mark()/_phase single-
    threaded on the main session."""
    ids = [c.id for c in companies]
    if not ids:
        return
    workers = min(ENRICH_MAX_WORKERS, len(ids))
    with _futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="enrich") as pool:
        futures = [
            pool.submit(_enrich_one, cid, campaign_id, owner_id, force_ai) for cid in ids
        ]
        for f in _futures.as_completed(futures):
            f.result()  # _enrich_one never raises; drain so the pool joins cleanly


# Keys that can be triggered on-demand for a single campaign. "meeting" is
# excluded because it's only ever triggered by the user booking a meeting in the
# Conversations UI — there's nothing for it to "run" otherwise.
RUNNABLE_KEYS = {
    "enrichment", "scoring", "employee_finder",
    "email_guess_verification", "outreach", "tracking",
}


# Pipeline output order — index drives "successors" for the cascade.
_OUTPUT_ORDER = [
    "enrichment", "scoring", "employee_finder",
    "email_guess_verification", "outreach",
]
_AGENT_NAMES = {key: name for key, name, _ in AGENT_REGISTRY}


def _qualified_companies(db: Session, campaign: Campaign) -> list[Company]:
    return (
        db.query(Company)
        .filter(Company.campaign_id == campaign.id, Company.status == "Qualified")
        .order_by(Company.rank)
        .limit(campaign.top_n)
        .all()
    )


def _walk_for_contactable(
    db: Session, campaign: Campaign, owner_id: int, force: bool = False,
) -> list[Company]:
    """Walk the campaign's ranked companies and run the employee finder until
    `campaign.top_n` have at least one contact. Companies that yield nothing
    are demoted Qualified → Reviewed, and the next-best Reviewed company by
    rank is promoted into the slot. Stops when we either fill the quota or
    exhaust every scored company.

    This is the fallback behavior the user asked for: "if no contact found
    for a specific company, take the next company from scoring."

    `force=True` is a full reset — every contact in the campaign is deleted
    up front (so previously-Qualified-but-now-Reviewed companies don't keep
    stale rows in the UI) and then the walker re-searches from rank 1. This
    is what the per-agent "Re-run" button on the campaign timeline sends.
    """
    if force:
        # Forced re-run wipes contacts for a clean picture — but NEVER a locked
        # contact (one with a sent Thread): its conversation must survive. CASCADE
        # wipes the deleted contacts' drafts.
        locked = locked_contact_ids(db, campaign.id)
        stale_contacts = (
            db.query(Contact)
            .join(Company, Company.id == Contact.company_id)
            .filter(Company.campaign_id == campaign.id)
            .all()
        )
        for ct in stale_contacts:
            if ct.id not in locked:
                db.delete(ct)
        db.commit()

    candidates = (
        db.query(Company)
        .filter(
            Company.campaign_id == campaign.id,
            Company.ai_score > 0,
            Company.status.in_(("Qualified", "Reviewed")),
        )
        .order_by(Company.rank)
        .all()
    )

    target = max(1, campaign.top_n)
    contactable: list[Company] = []

    for c in candidates:
        if len(contactable) >= target:
            # Quota filled — any remaining Qualified rows below this point
            # need to be demoted so verification/outreach don't pick them up.
            if c.status == "Qualified":
                c.status = "Reviewed"
            continue

        if not c.contacts or force:
            # Reuse first: a company already in the verified-contact directory is
            # seeded directly (Verified contacts) and the finder is skipped.
            if not contact_directory.seed_company(db, c):
                try:
                    employee_finder_agent.run(db, c, owner_id, force=force)
                except Exception:
                    pass
            db.refresh(c)

        if c.contacts:
            if c.status != "Qualified":
                c.status = "Qualified"
            contactable.append(c)
        else:
            if c.status == "Qualified":
                c.status = "Reviewed"

    db.commit()
    return contactable


def _reset_scoring_fields(db: Session, campaign: Campaign) -> None:
    """Clear scoring's output. Preserve user-set statuses (Excluded/Approved/
    Contacted); only automatic Qualified/Reviewed fall back to Researching."""
    for c in db.query(Company).filter(Company.campaign_id == campaign.id):
        c.ai_score = 0
        c.rank = 0
        c.match_level = "Moderate"
        c.match_explanation = ""
        c.score_factors = []
        if c.status in ("Qualified", "Reviewed"):
            c.status = "Researching"


def _delete_non_locked_contacts(db: Session, campaign: Campaign) -> None:
    """Delete every contact in the campaign that has no Thread (CASCADE removes
    their drafts). Locked contacts (sent conversations) are preserved."""
    locked = locked_contact_ids(db, campaign.id)
    contacts = (
        db.query(Contact).join(Company, Company.id == Contact.company_id)
        .filter(Company.campaign_id == campaign.id).all()
    )
    for c in contacts:
        if c.id not in locked:
            db.delete(c)


def _delete_non_locked_drafts(db: Session, campaign: Campaign) -> None:
    """Delete drafts belonging to non-locked contacts (outreach output)."""
    locked = locked_contact_ids(db, campaign.id)
    drafts = (
        db.query(EmailDraft)
        .join(Contact, Contact.id == EmailDraft.contact_id)
        .join(Company, Company.id == Contact.company_id)
        .filter(Company.campaign_id == campaign.id).all()
    )
    for d in drafts:
        if d.contact_id not in locked:
            db.delete(d)


def clear_successors(db: Session, campaign: Campaign, from_key: str) -> None:
    """Clear the output of every output-agent AFTER `from_key`, preserving locked
    contacts (sent conversations) and meetings. See the design spec's cascade map."""
    if from_key not in _OUTPUT_ORDER:
        return
    successors = set(_OUTPUT_ORDER[_OUTPUT_ORDER.index(from_key) + 1:])
    if "scoring" in successors:
        _reset_scoring_fields(db, campaign)
    if "employee_finder" in successors:
        _delete_non_locked_contacts(db, campaign)  # CASCADE clears their drafts
    elif "outreach" in successors:
        _delete_non_locked_drafts(db, campaign)
    db.commit()


def run_agent_for_campaign(
    db: Session, campaign: Campaign, owner_id: int, key: str, force: bool = False,
) -> None:
    """Run a single agent for a single campaign. The pipeline above is just a
    fixed sequence of these calls — this helper lets the UI trigger any stage
    independently (e.g. "re-score" without re-enriching).

    `force=True` tells the underlying agent to discard its prior output (stale
    contacts, stale email drafts, stale verification verdicts) and produce a
    fresh result. Defaults to False so bulk pipelines stay incremental.
    """
    # Non-approved users get a credit-capped version of the free agents (the API
    # 403s the gated ones). No snapshot/cascade — the capped run is cheap.
    user = db.get(User, owner_id)
    if user and not user.has_access:
        _run_agent_capped(db, campaign, owner_id, key, force)
        return

    # A forced re-run is destructive: snapshot for undo, then clear this agent's
    # successors (preserving locked conversations). Non-forced incremental runs
    # are additive — no snapshot, no cascade.
    if force and key in _OUTPUT_ORDER:
        snapshots.capture(
            db, campaign, owner_id,
            trigger=f"agent:{key}", label=f"Re-run: {_AGENT_NAMES.get(key, key)}",
        )
        clear_successors(db, campaign, key)

    companies = db.query(Company).filter(Company.campaign_id == campaign.id).all()

    if key == "enrichment":
        # Enrichment uses `force_ai` (single flag — it both means "run AI even
        # for dead/parked domains" and "redo the search instead of reusing
        # cached summary"). Tie it to the same `force` toggle. Fan out across a
        # bounded pool so a large campaign isn't researched one company at a time.
        _phase(
            db, owner_id, enrichment_agent,
            lambda: _run_enrichment_concurrent(companies, campaign.id, owner_id, force_ai=force),
        )
    elif key == "scoring":
        _phase(db, owner_id, scoring_agent, lambda: scoring_agent.run(db, campaign, owner_id))
    elif key == "employee_finder":
        # Walk down the rank list — if a Qualified company has no real
        # LinkedIn contacts, demote it and try the next-best Reviewed
        # company. With force=True, each candidate's prior contacts are
        # wiped first so a real re-search runs.
        _phase(
            db, owner_id, employee_finder_agent,
            lambda: _walk_for_contactable(db, campaign, owner_id, force=force),
        )
    elif key == "email_guess_verification":
        # The merged agent guesses (guess_emails per contact) then verifies in
        # one pass, so a single key drives both.
        qualified = _qualified_companies(db, campaign)
        _phase(
            db, owner_id, email_guess_verification_agent,
            lambda: [email_guess_verification_agent.run(db, c, owner_id, force=force) for c in qualified],
        )
    elif key == "outreach":
        qualified = _qualified_companies(db, campaign)

        def _draft_all() -> None:
            for c in qualified:
                for contact in c.contacts:
                    # Draft only for contacts that actually have an address
                    # (provider-verified or human-edited). No address → skip.
                    if (
                        (contact.email or "").strip()
                        and contact.approved is not False
                        and not contact.do_not_contact
                        and not is_locked(db, contact)  # already in conversation
                    ):
                        outreach_agent.run(db, contact, c, campaign, owner_id, force=force)

        nudge_missing_company(db, owner_id)
        _phase(db, owner_id, outreach_agent, _draft_all)
    elif key == "tracking":
        # Tracking is user-scoped, not campaign-scoped — the agent walks all
        # the user's Running threads. Triggering it here runs it for everyone.
        _phase(db, owner_id, tracking_agent, lambda: tracking_agent.run(db, owner_id))
    else:
        raise ValueError(f"Agent '{key}' cannot be run on demand")


def _preview_companies(db: Session, campaign: Campaign) -> list[Company]:
    """First PREVIEW_COMPANIES companies (upload order) — the non-approved sample."""
    return (
        db.query(Company)
        .filter(Company.campaign_id == campaign.id)
        .order_by(Company.id)
        .limit(PREVIEW_COMPANIES)
        .all()
    )


def _find_one_contact(db: Session, company: Company, owner_id: int, force: bool) -> None:
    """Find a single contact for `company` — the non-approved contact cap."""
    # Cap the search ladder: we only keep ONE contact, so collecting the finder's
    # default 8 candidates would burn search credits for profiles we discard. A
    # small target stops the escalating queries after a hit or two while still
    # giving the AI ranker a couple of candidates to choose the best from.
    employee_finder_agent.run(db, company, owner_id, count=1, force=force, search_target=3)
    db.refresh(company)
    for extra in company.contacts[1:]:  # guard: keep exactly one
        db.delete(extra)
    db.commit()


def _run_agent_capped(
    db: Session, campaign: Campaign, owner_id: int, key: str, force: bool
) -> None:
    """One free agent, credit-capped, for a non-approved user (2 companies / 1
    contact). Gated keys never reach here — the API 403s them for non-approved."""
    companies = _preview_companies(db, campaign)
    if not companies:
        return
    if key == "enrichment":
        _phase(
            db, owner_id, enrichment_agent,
            lambda: _run_enrichment_concurrent(companies, campaign.id, owner_id, force_ai=force),
        )
    elif key == "scoring":
        _phase(
            db, owner_id, scoring_agent,
            lambda: scoring_agent.run(db, campaign, owner_id, companies=companies),
        )
    elif key == "employee_finder":
        top = max(companies, key=lambda c: c.ai_score or 0)
        _phase(db, owner_id, employee_finder_agent, lambda: _find_one_contact(db, top, owner_id, force))
    elif key == "email_guess_verification":
        top = max(companies, key=lambda c: c.ai_score or 0)
        _phase(
            db, owner_id, email_guess_verification_agent,
            lambda: email_guess_verification_agent.run(db, top, owner_id, force=force),
        )


def _run_preview_pipeline(db: Session, campaign: Campaign, owner_id: int) -> dict:
    """Credit-capped full run for non-approved users: enrich + score the first
    PREVIEW_COMPANIES companies, then ONE contact (and its email) for the
    top-scored one. Never reaches outreach."""
    companies = _preview_companies(db, campaign)
    if not companies:
        return {"companies": 0, "qualified": 0, "contacts": 0}

    _phase(
        db, owner_id, enrichment_agent,
        lambda: _run_enrichment_concurrent(companies, campaign.id, owner_id, force_ai=False),
    )
    _phase(
        db, owner_id, scoring_agent,
        lambda: scoring_agent.run(db, campaign, owner_id, companies=companies),
    )

    top = max(companies, key=lambda c: c.ai_score or 0)
    _phase(db, owner_id, employee_finder_agent, lambda: _find_one_contact(db, top, owner_id, True))
    db.refresh(top)
    if top.contacts:
        _phase(
            db, owner_id, email_guess_verification_agent,
            lambda: email_guess_verification_agent.run(db, top, owner_id, force=True),
        )

    campaign.status = "Running"
    db.commit()
    add_notification(
        db, owner_id, "campaign", "Preview ready",
        f"'{campaign.name}': previewed {len(companies)} companies. Request access for the full run.",
    )
    return {
        "companies": len(companies),
        "qualified": len(companies),
        "contacts": sum(len(c.contacts) for c in companies),
    }


def run_campaign_pipeline(db: Session, campaign: Campaign, owner_id: int) -> dict:
    """Phases 1–6: research → score → contacts → guess/verify → outreach drafts.
    Non-approved users get the credit-capped preview instead (see _run_preview_pipeline)."""
    user = db.get(User, owner_id)
    if user and not user.has_access:
        return _run_preview_pipeline(db, campaign, owner_id)

    snapshots.capture(db, campaign, owner_id, trigger="pipeline", label="Full pipeline run")
    companies = db.query(Company).filter(Company.campaign_id == campaign.id).all()

    # Phase 1 — enrichment (concurrent: one private session per worker, bounded
    # pool). force_ai=False — the bulk path still skips AI for dead/parked domains.
    _phase(
        db, owner_id, enrichment_agent,
        lambda: _run_enrichment_concurrent(companies, campaign.id, owner_id, force_ai=False),
    )

    # Phase 2 — scoring + ranking
    _phase(db, owner_id, scoring_agent, lambda: scoring_agent.run(db, campaign, owner_id))

    # Phase 3 — employee finder. Walks down the ranked list and fills the
    # top_n slots with companies that actually yielded LinkedIn contacts; any
    # company that came up empty is demoted to Reviewed and the next-best
    # candidate is tried in its place.
    #
    # `force=True` here means a "Run all agents" click wipes every contact in
    # the campaign before re-searching. Without this, contacts that belonged
    # to companies which scoring just demoted to Reviewed would linger and
    # the user perceives the finder as "not running again".
    contactable: list[Company] = []

    def _run_finder() -> None:
        nonlocal contactable
        contactable = _walk_for_contactable(db, campaign, owner_id, force=True)

    _phase(db, owner_id, employee_finder_agent, _run_finder)

    # Phases 4 & 5 — email guessing + verification (operate on the now-final
    # contactable set, not the pre-walk Qualified list). force=True so the
    # newly-found contacts get a fresh email + verification verdict rather
    # than the stale state inherited from prior runs.
    _phase(
        db, owner_id, email_guess_verification_agent,
        lambda: [email_guess_verification_agent.run(db, c, owner_id, force=True) for c in contactable],
    )

    # Phase 6 — outreach drafts for verified/contactable contacts. force=True
    # so each draft is regenerated against the latest enrichment summary.
    def _draft_all():
        for c in contactable:
            for contact in c.contacts:
                # Draft only for contacts with a real address (see run-agent path).
                if (
                    (contact.email or "").strip()
                    and contact.approved is not False
                    and not contact.do_not_contact
                    and not is_locked(db, contact)  # already in conversation
                ):
                    outreach_agent.run(db, contact, c, campaign, owner_id, force=True)

    # Only approved users reach here (non-approved branch to the preview above).
    nudge_missing_company(db, owner_id)
    _phase(db, owner_id, outreach_agent, _draft_all)

    campaign.status = "Running"
    db.commit()
    add_notification(
        db, owner_id, "campaign",
        "Pipeline complete",
        f"'{campaign.name}' researched, scored, and drafted. Review and send.",
    )
    return {
        "companies": len(companies),
        "qualified": len(contactable),
        "contacts": sum(len(c.contacts) for c in contactable),
    }
