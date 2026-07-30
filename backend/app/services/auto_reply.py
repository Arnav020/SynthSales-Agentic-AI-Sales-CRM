"""Autonomous reply handlers.

Invoked by reply_classifier ONLY when the user has autonomous_replies on and the
safety gates pass (see the spec). Each handler composes a real outbound email,
sends it, and updates thread/contact state. Reuses the AI, meeting, and email
providers. Never bypasses the gates; callers wrap handle() in try/except and fall
back to surfacing on any error.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Campaign, Contact, Meeting, Message, Thread, User, utcnow
from app.providers.ai import ai
from app.providers.email import email_provider
from app.agents.meeting import meeting_agent
from app.services.events import add_notification

ACTIONABLE_INTENTS = {"interested", "meeting_ready", "not_interested", "question"}


def gates_pass(owner: User, contact: Contact | None, verdict: dict) -> bool:
    """All four gates from the spec, plus an actionable intent."""
    try:
        confidence = int(verdict.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    return bool(
        owner.outbound_enabled
        and owner.autonomous_replies
        and contact
        and contact.email
        and not contact.do_not_contact
        and verdict.get("intent") in ACTIONABLE_INTENTS
        and confidence >= settings.reply_optout_min_confidence
    )


def handle(
    db: Session, owner: User, thread: Thread, contact: Contact,
    campaign: Campaign | None, verdict: dict,
) -> str:
    """Dispatch to the matching handler. Returns the handler name (for logging)."""
    intent = verdict["intent"]
    if intent == "not_interested":
        return _closing_note(db, owner, thread, contact, campaign, verdict)
    if intent in ("interested", "meeting_ready"):
        return _propose_and_book(db, owner, thread, contact, campaign, verdict)
    if intent == "question":
        return _answer_question(db, owner, thread, contact, campaign, verdict)
    return "noop"


# ---- shared helpers -------------------------------------------------------
def _first_name(contact: Contact) -> str:
    return (contact.name or "there").split(" ")[0]


def _reply_subject(thread: Thread) -> str:
    subj = thread.subject or "Following up"
    return subj if subj.lower().startswith("re:") else f"Re: {subj}"


def _at(owner: User) -> str:
    """' at <company>' when the user has set their company in Settings, else ''.
    Keeps the SDR persona anonymous rather than letting the model invent a name."""
    sender = (owner.company_name or "").strip()
    return f" at {sender}" if sender else ""


def _compose(prompt: str, system: str, fallback: str) -> str:
    if ai.available:
        text = ai.complete(prompt, system=system, max_tokens=400)
        if text:
            return text.strip()
    return fallback


def _record_us(db: Session, thread: Thread, subject: str, body: str) -> None:
    db.add(Message(
        thread_id=thread.id, direction="us", author="SynthSales (auto)",
        subject=subject, body=body,
    ))
    thread.last_activity = utcnow()


def _strip_quoted(body: str) -> str:
    """Drop the quoted reply history mail clients append, so AI prompts read only
    the prospect's new text (and don't, e.g., re-parse our own quoted proposed time)."""
    cuts = [
        m.start()
        for p in (
            re.compile(r"\n\s*On\b[\s\S]{0,200}?\bwrote:"),
            re.compile(r"\n\s*>"),
            re.compile(r"\n-{2,}\s*Original Message", re.IGNORECASE),
            re.compile(r"\n_{5,}"),
        )
        if (m := p.search(body or ""))
    ]
    if not cuts:
        return (body or "").strip()
    return body[: min(cuts)].strip() or (body or "").strip()


def _default_slot() -> datetime:
    """Second business day from now at 10:00 UTC (skip Sat/Sun)."""
    d = utcnow().date()
    added = 0
    while added < 2:
        d = d + timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            added += 1
    return datetime.combine(d, time(10, 0), tzinfo=timezone.utc)


def _requested_time(thread: Thread) -> datetime | None:
    """If the prospect's latest reply names a specific date/time, parse it (via the
    AI) into a future UTC datetime; otherwise None so the caller uses the default
    slot. Never invents a time the prospect didn't state."""
    if not ai.available:
        return None
    last_them = next(
        (m for m in reversed(thread.messages) if m.direction == "them"), None
    )
    if not last_them or not (last_them.body or "").strip():
        return None
    anchor = last_them.sent_at or utcnow()
    data = ai.complete_json(
        prompt=(
            f"The prospect sent this reply at {anchor:%A, %Y-%m-%d %H:%M} UTC, about "
            f"scheduling an intro call. If it names a SPECIFIC date and/or time, return it "
            f"as ISO-8601 UTC (resolve relative terms like 'tomorrow' or 'next Monday' "
            f"against that send time). If no concrete time is requested, return null. "
            f"Never invent a time.\n\nReply:\n{_strip_quoted(last_them.body)[:600]}\n\n"
            'Return JSON only: {"datetime_utc": "YYYY-MM-DDTHH:MM:SSZ" | null}'
        ),
        system="You extract a requested meeting time. Output strict JSON only, in UTC.",
    )
    if not isinstance(data, dict):
        return None
    raw = data.get("datetime_utc")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt if dt > utcnow() else None


def _closing_note(db, owner, thread, contact, campaign, verdict) -> str:
    first = _first_name(contact)
    company = contact.company.name if contact.company else "your team"
    body = _compose(
        prompt=(
            f"A prospect named {contact.name} replied that they are not interested. "
            f"Write a brief (2-3 sentence), warm, no-pressure closing reply that thanks "
            f"them, respects the no, and leaves the door open. No signature."
        ),
        system=f"You are a gracious B2B SDR{_at(owner)}.",
        fallback=(
            f"Thanks for the reply, {first} — completely understand, and I appreciate "
            f"you letting me know. I'll close the loop here; if anything changes down "
            f"the road, I'm just a reply away. Wishing you and {company} all the best."
        ),
    )
    subject = _reply_subject(thread)
    _record_us(db, thread, subject, body)
    contact.do_not_contact = True
    thread.stage = "Closed"
    add_notification(
        db, owner.id, "reply", "Auto-replied: not interested",
        f"'{thread.subject}' — sent a closing note and marked the contact do-not-contact.",
    )
    email_provider.send(contact.email, subject, body)
    return "closing_note"


def _propose_and_book(db, owner, thread, contact, campaign, verdict) -> str:
    # Honor a specific time the prospect asked for (e.g. a reschedule); otherwise
    # fall back to the default slot.
    when = _requested_time(thread) or _default_slot()
    # A pre-existing Upcoming meeting for this contact means this is a reschedule —
    # the reply should read as "moved", not a first invite.
    company_name = contact.company.name if contact and contact.company else thread.subject
    is_reschedule = bool(
        db.query(Meeting)
        .filter(
            Meeting.campaign_id == thread.campaign_id,
            Meeting.company == company_name,
            Meeting.contact == (contact.name if contact else "—"),
            Meeting.status == "Upcoming",
        )
        .first()
    )
    when_str = when.strftime("%A, %b %d at %I:%M %p UTC")
    product = (campaign.product if campaign else "") or "what we do"
    role = contact.role if contact and contact.role else "Contact"
    # A useful, human-readable meeting note (shown in the Meetings tab + the
    # calendar event description) instead of a terse "auto-scheduled" stub.
    note = (
        f"Auto-rescheduled to {when_str} at {contact.name}'s request. "
        f"{role} at {company_name}, re: {product}."
        if is_reschedule
        else (
            f"Auto-booked from {contact.name}'s interested reply. {role} at {company_name}, "
            f"interested in {product}. Call proposed for {when_str}."
        )
    )
    # notify=False: create the event + Meet link, suppress Google's invite and
    # book()'s own email; we send one branded email below. book() still sets the
    # thread to Meeting and records the meeting.
    meeting = meeting_agent.book(
        db, thread, owner, when, link=None, notes=note, notify=False, announce=False,
    )
    first = _first_name(contact)
    if is_reschedule:
        body = _compose(
            prompt=(
                f"A prospect named {contact.name} asked to reschedule the intro call about "
                f"{product}. Write a short, warm reply that clearly confirms you've MOVED the "
                f"call to {when_str} (a reschedule of an existing call, NOT a first invite), "
                f"shares the updated Google Meet link {meeting.link}, and invites them to reply "
                f"if that still doesn't work. Under 90 words. No signature."
            ),
            system=f"You are a helpful B2B SDR{_at(owner)}.",
            fallback=(
                f"No problem, {first} — I've moved our call to {when_str}. Here's the updated "
                f"Google Meet link: {meeting.link}\n\nIf that time still doesn't suit, just let "
                f"me know."
            ),
        )
        notif_title, notif_detail = (
            "Auto-rescheduled meeting",
            f"'{thread.subject}' — moved the call to {when_str}.",
        )
    else:
        body = _compose(
            prompt=(
                f"A prospect named {contact.name} is interested in {product}. Write a short, "
                f"warm reply that says you've set up a quick intro call for {when_str}, invites "
                f"them to reply if another time suits, and tells them the Google Meet join link "
                f"is {meeting.link}. Keep it under 90 words. No signature."
            ),
            system=f"You are a helpful B2B SDR{_at(owner)}.",
            fallback=(
                f"Great to hear, {first}! I've set up a quick intro call for {when_str}. "
                f"Join link: {meeting.link}\n\nIf another time works better, just reply and "
                f"I'll move it."
            ),
        )
        notif_title, notif_detail = (
            "Auto-booked from interested reply",
            f"'{thread.subject}' — proposed {when_str} and sent the Meet link.",
        )
    if meeting.link and meeting.link not in body:
        body = body.rstrip() + f"\n\nJoin link: {meeting.link}"
    subject = _reply_subject(thread)
    _record_us(db, thread, subject, body)
    add_notification(db, owner.id, "meeting", notif_title, notif_detail)
    email_provider.send(contact.email, subject, body)
    return "propose_and_book"


def _answer_question(db, owner, thread, contact, campaign, verdict) -> str:
    parts: list[str] = []
    if campaign:
        if campaign.product:
            parts.append(f"Product: {campaign.product}")
        if campaign.product_description:
            parts.append(f"Description: {campaign.product_description}")
        if campaign.value_proposition:
            parts.append(f"Value proposition: {campaign.value_proposition}")
        if campaign.differentiators:
            parts.append(f"Differentiators: {campaign.differentiators}")
        if campaign.business_requirements:
            parts.append(f"Business requirements served: {campaign.business_requirements}")
    product_info = "\n".join(parts)
    question = ""
    last_them = next(
        (m for m in reversed(thread.messages) if m.direction == "them"), None
    )
    if last_them:
        question = _strip_quoted(last_them.body)[:1500]

    data = ai.complete_json(
        prompt=(
            "You are answering a prospect's question using ONLY the product info below. "
            "If the info fully answers it, return a concise answer; if it does NOT, set "
            'answerable=false.\n\n'
            f"PRODUCT INFO:\n{product_info}\n\nPROSPECT QUESTION:\n{question}\n\n"
            'Return JSON: {"answerable": <true|false>, "answer": "<reply text, no signature>"}'
        ),
        system=f"You are a precise B2B SDR{_at(owner)} who never invents facts.",
    ) if ai.available else None

    answerable = bool(data and data.get("answerable") and (data.get("answer") or "").strip())
    if not answerable:
        # "we don't have it" -> message + meeting link
        return _propose_and_book(db, owner, thread, contact, campaign, verdict)

    body = str(data["answer"]).strip()
    cta = "\n\nHappy to walk through it on a quick call if useful — just say the word."
    if "call" not in body.lower():
        body = body + cta
    subject = _reply_subject(thread)
    _record_us(db, thread, subject, body)
    thread.stage = "Negotiating"
    add_notification(
        db, owner.id, "reply", "Auto-answered a question",
        f"'{thread.subject}' — answered from campaign product info.",
    )
    email_provider.send(contact.email, subject, body)
    return "answer_question"
