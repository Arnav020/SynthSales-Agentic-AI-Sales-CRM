from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.agents.base import Agent
from app.core.config import settings
from app.models import Campaign, Contact, Message, Thread, User, utcnow
from app.providers.ai import ai
from app.providers.email import email_provider
from app.services.events import add_notification


class TrackingAgent(Agent):
    key = "tracking"
    name = "Email Tracking & Follow-up"

    def suggestion_for(self, thread: Thread) -> str | None:
        """Contextual AI reply suggestion when the lead has replied."""
        if not thread.messages:
            return None
        last = thread.messages[-1]
        if last.direction != "them":
            return None
        if ai.available:
            convo = "\n".join(f"{m.direction}: {m.body}" for m in thread.messages[-4:])
            s = ai.complete(
                f"Thread so far:\n{convo}\n\nSuggest a concise next reply that moves "
                "toward booking a meeting.",
                system="You are a helpful B2B sales assistant.",
                max_tokens=300,
            )
            if s:
                return s
        return (
            "They replied — propose two concrete time slots this week and offer to "
            "tailor the demo to their use case."
        )

    def run(self, db: Session, owner_id: int) -> int:
        """Send automatic follow-ups for stale, unanswered outbound threads, and
        auto-stall threads that never reply after the follow-up cap."""
        # Respect the user's outbound kill-switch — no auto follow-ups while paused.
        owner = db.get(User, owner_id)
        if not owner or not owner.outbound_enabled:
            return 0
        # Staleness is measured in DAYS now, independent of how often we poll.
        cutoff = utcnow() - timedelta(days=settings.followup_delay_days)
        threads = (
            db.query(Thread)
            .join(Campaign, Campaign.id == Thread.campaign_id)
            .filter(Campaign.owner_id == owner_id, Campaign.status == "Running")
            .all()
        )
        sent = 0
        stalled = 0
        for t in threads:
            if t.stage != "Contacted" or not t.messages:
                continue
            # Suppressed contacts are skipped entirely (do-not-contact).
            contact = db.get(Contact, t.contact_id) if t.contact_id else None
            if contact and contact.do_not_contact:
                continue
            last = t.messages[-1]
            # Only act when WE spoke last and it's gone unanswered past the delay.
            if last.direction != "us" or last.sent_at >= cutoff:
                continue
            follow_ups = sum(1 for m in t.messages if m.is_follow_up)
            if follow_ups < settings.max_follow_ups:
                self._send_follow_up(db, t, owner_id)
                sent += 1
            else:
                # Cap reached and still no reply → terminal stall (no more outreach).
                t.stage = "Stalled"
                t.last_activity = utcnow()
                db.commit()
                add_notification(
                    db,
                    owner_id,
                    "followup",
                    "Thread stalled",
                    f"'{t.subject}' — no reply after {settings.max_follow_ups} follow-ups.",
                )
                stalled += 1
        if sent or stalled:
            self.log(db, owner_id, f"Sent {sent} follow-up(s); stalled {stalled} thread(s).")
        return sent

    def _send_follow_up(self, db: Session, thread: Thread, owner_id: int) -> None:
        if ai.available:
            owner = db.get(User, owner_id)
            sender = (owner.company_name or "").strip() if owner else ""
            convo = "\n".join(f"{m.direction}: {m.body}" for m in thread.messages[-3:])
            body = ai.complete(
                f"Prior thread:\n{convo}\n\nWrite a brief, polite follow-up nudge.",
                system=(
                    f"You are a B2B SDR{' at ' + sender if sender else ''}. "
                    "Keep it under 80 words."
                ),
                max_tokens=250,
            )
        else:
            body = ""
        body = body or (
            "Just floating this back to the top of your inbox — happy to send a short "
            "overview or find 20 minutes that works. Would later this week suit you?"
        )
        msg = Message(
            thread_id=thread.id,
            direction="us",
            author="SynthSales (auto)",
            body=body,
            is_follow_up=True,
        )
        db.add(msg)
        thread.last_activity = utcnow()
        # Resolve the recipient from the thread's contact; only send if we have
        # a real address (the thread's contact may have no verified email).
        contact = db.get(Contact, thread.contact_id) if thread.contact_id else None
        if contact and contact.email:
            email_provider.send(contact.email, thread.subject or "Following up", body)
        db.commit()
        add_notification(
            db,
            owner_id,
            "followup",
            "Follow-up sent automatically",
            f"Thread '{thread.subject}' — no reply after "
            f"{settings.followup_delay_days} days.",
        )


tracking_agent = TrackingAgent()
