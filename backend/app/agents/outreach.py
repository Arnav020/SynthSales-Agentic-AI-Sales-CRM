from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.agents.base import Agent
from app.models import Campaign, Company, Contact, EmailDraft
from app.providers.ai import ai

# Unfilled template artifacts that must never reach a prospect: bracketed
# fill-ins ("[Your Company]", "[briefly mention ...]"), {{merge}} fields, and
# <Angle> placeholders (the @-exclusion keeps "<max@x.io>" legal).
_PLACEHOLDER_RE = re.compile(
    r"\[[^\[\]\n]{2,}\]"
    r"|\{\{[^{}\n]+\}\}"
    r"|<[A-Z][^<>@\n]{2,}>"
)


def _looks_templated(text: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(text))


class OutreachAgent(Agent):
    key = "outreach"
    name = "Outreach Generation"

    def run(
        self,
        db: Session,
        contact: Contact,
        company: Company,
        campaign: Campaign,
        owner_id: int,
        force: bool = False,
    ) -> EmailDraft:
        existing = (
            db.query(EmailDraft).filter(EmailDraft.contact_id == contact.id).first()
        )
        if existing and not force:
            return existing
        if existing and force:
            db.delete(existing)
            db.commit()

        subject, body = self._generate(contact, company, campaign)
        footer = campaign.footer or "Best regards,\nThe SynthSales Team"
        draft = EmailDraft(
            contact_id=contact.id,
            subject=subject,
            body=body,
            footer=footer,
            state="Queued",
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)
        self.log(db, owner_id, f"Drafted outreach to {contact.name} ({company.name}).")
        return draft

    def _generate(self, contact: Contact, company: Company, campaign: Campaign) -> tuple[str, str]:
        if ai.available:
            base_prompt = (
                f"Write a short, personalized cold outreach email.\n"
                f"Recipient: {contact.name}, {contact.role} at {company.name}.\n"
                f"Company research: {company.research_summary}\n"
                f"We sell: {campaign.product} — {campaign.value_proposition or campaign.product_description}\n"
                f"Tone: {campaign.tone}. Personalization level: {campaign.personalization_level}/3.\n"
                f"{'Use this template: ' + campaign.email_template if campaign.email_template else ''}\n"
                "Rules: the email must be final copy, ready to send exactly as written. "
                "Never use placeholders, bracketed fill-ins, or merge fields (no "
                "'[Your Company]', no '[briefly mention ...]', no '{{name}}'). Refer to "
                "the sender as 'we' — do not invent a sender company name. If the "
                "product info above is thin, keep the pitch to one short sentence using "
                "only what is given rather than padding with template text.\n"
                "Return JSON with keys: subject (string) and body (string, no signature)."
            )
            prompt = base_prompt
            # One corrective retry: a draft with unfilled placeholders must never
            # be stored, but a single nudge usually salvages the personalization
            # that the deterministic fallback would lose.
            for _ in range(2):
                data = ai.complete_json(prompt, system="You are an expert B2B SDR copywriter.")
                if not data:
                    break
                subject = str(data.get("subject") or "")
                body = str(data.get("body") or "")
                if subject and body and not _looks_templated(f"{subject}\n{body}"):
                    return subject, body
                prompt = (
                    "Your previous draft contained unfilled placeholder text. Rewrite "
                    "it as final, ready-to-send copy with no placeholders.\n\n"
                    + base_prompt
                )

        # Deterministic fallback template.
        first = contact.name.split(" ")[0]
        subject = f"{campaign.product or 'A quick idea'} for {company.name}"
        body = (
            f"Hi {first},\n\n"
            f"I came across {company.name} while researching leaders in {company.industry}. "
            f"{company.research_summary.split('.')[0]}.\n\n"
            f"We help teams like yours with {campaign.product or 'our solution'} — "
            f"{campaign.value_proposition or campaign.product_description or 'measurable results, fast'}.\n\n"
            f"Would a brief 20-minute call next week be worth your time, {first}?"
        )
        return subject, body


outreach_agent = OutreachAgent()
