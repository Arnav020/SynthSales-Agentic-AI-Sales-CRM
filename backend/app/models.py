"""SQLAlchemy models for the SynthSales platform.

Core tables (per PRD §4 DB design): Users, Campaigns, Companies, Contacts,
Email Threads + Messages, Email Drafts, Meetings, Notifications, Logs, Agents.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    # The user's own company — the sender identity for every AI-composed email
    # (outreach drafts, follow-ups, autonomous replies). Empty ⇒ prompts fall
    # back to an anonymous "we"; they must never invent a name.
    company_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Outbound email kill-switch. Starts OFF so no real emails go to prospects
    # until the user explicitly enables sending in Settings.
    outbound_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Autonomous reply kill-switch. Starts OFF: when off the reply-classifier only
    # surfaces inbound replies (today's behavior). When ON (and outbound_enabled is
    # also on), high-confidence replies are answered automatically. See the spec.
    autonomous_replies: Mapped[bool] = mapped_column(Boolean, default=False)
    # Admin role — grants access to the cross-tenant /api/admin/* routes
    # (read or delete any user's data). Bootstrap the first admin by setting
    # this column true directly in the DB (see README / db.ps1).
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # Stored with a provenance prefix ("V" = signup verification, "R" = password
    # reset) so a code issued by one flow can never be consumed by the other.
    otp_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Wrong-code counter for the current OTP. Reset to 0 whenever a fresh code is
    # issued (register / resend) and on successful verification. Once it hits
    # MAX_OTP_ATTEMPTS the code is locked until a new one is requested — stops a
    # 6-digit code from being brute-forced before it expires.
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Google account subject ("sub") when the user signed in via Google OAuth.
    # Null for password-only accounts. Presence ⇒ the account is Google-linked.
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # Per-user Google refresh token for the calendar.events scope — booking creates
    # a real Meet link on THIS user's calendar. Sensitive: never serialized into
    # UserOut/logs/WS. Presence ⇒ calendar_connected.
    google_calendar_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-user Google refresh token for the gmail.readonly scope — lets the
    # inbound poller read THIS user's replies. Sensitive: never serialized into
    # UserOut/logs/WS. Presence ⇒ mailbox_connected.
    gmail_read_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Anti-abuse access gating. New accounts start "none" (research + list-building
    # only); "approved" unlocks the outreach agents + outbound sending. Admins are
    # always treated as approved (see has_access). Existing users were grandfathered
    # to "approved" by the adopting migration.
    access_status: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    access_note: Mapped[str | None] = mapped_column(Text, nullable=True)          # user's justification
    access_review_note: Mapped[str | None] = mapped_column(Text, nullable=True)   # admin's reason
    access_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def calendar_connected(self) -> bool:
        return bool(self.google_calendar_token)

    @property
    def mailbox_connected(self) -> bool:
        return bool(self.gmail_read_token)

    @property
    def has_access(self) -> bool:
        """Admins are implicitly approved; everyone else needs an explicit grant."""
        return bool(self.is_admin or self.access_status == "approved")

    campaigns: Mapped[list[Campaign]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    product: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default="Draft")
    tone: Mapped[str] = mapped_column(String(40), default="professional")
    top_n: Mapped[int] = mapped_column(Integer, default=50)

    # Product details
    product_description: Mapped[str] = mapped_column(Text, default="")
    value_proposition: Mapped[str] = mapped_column(Text, default="")
    industry: Mapped[str] = mapped_column(String(120), default="")
    differentiators: Mapped[str] = mapped_column(Text, default="")

    # Target requirements
    icp: Mapped[str] = mapped_column(Text, default="")
    industry_pref: Mapped[str] = mapped_column(String(600), default="")
    geography: Mapped[str] = mapped_column(String(400), default="")
    company_size: Mapped[str] = mapped_column(String(120), default="")
    business_requirements: Mapped[str] = mapped_column(Text, default="")
    ranking_criteria: Mapped[str] = mapped_column(Text, default="")

    # Outreach settings
    email_template: Mapped[str] = mapped_column(Text, default="")
    footer: Mapped[str] = mapped_column(Text, default="")
    personalization_level: Mapped[int] = mapped_column(Integer, default=2)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship(back_populates="campaigns")
    companies: Mapped[list[Company]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    meetings: Mapped[list[Meeting]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(200), default="")
    # Optional explicit mail-domain override (the part after '@'), for companies
    # whose email domain differs from the website (e.g. notion.so → makenotion.com)
    # and can't be auto-discovered. When set, the guess-verify agent uses it.
    mail_domain: Mapped[str] = mapped_column(String(200), default="")
    industry: Mapped[str] = mapped_column(String(120), default="")
    size: Mapped[str] = mapped_column(String(40), default="")
    location: Mapped[str] = mapped_column(String(120), default="")

    ai_score: Mapped[int] = mapped_column(Integer, default=0)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    match_level: Mapped[str] = mapped_column(String(20), default="Moderate")
    status: Mapped[str] = mapped_column(String(20), default="Researching")

    research_summary: Mapped[str] = mapped_column(Text, default="")
    # 5–8 bullet research profile — the new primary narrative shown to the user.
    # research_summary is auto-derived from these (space-joined) so existing
    # consumers (outreach prompt, pipeline stats, admin debug, seed) keep working.
    research_points: Mapped[list] = mapped_column(JSONB, default=list)
    match_explanation: Mapped[str] = mapped_column(Text, default="")
    score_factors: Mapped[list] = mapped_column(JSONB, default=list)
    recent_funding: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recent_news: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_hiring: Mapped[bool] = mapped_column(Boolean, default=False)
    # 0–100: how much real evidence backs the enrichment. Low means dead domain,
    # no search hits, or AI couldn't find supporting signals. Scoring uses this
    # to cap fabricated/low-evidence companies away from "Strong".
    enrichment_confidence: Mapped[int] = mapped_column(Integer, default=50)
    # INTERNAL backend-only signal — NOT exposed in CompanyOut / frontend.
    # Per-metric 0–100 confidence for each AI-filled field (keys: industry, size,
    # location, recent_funding, recent_news, active_hiring, summary). Scoring
    # DISCOUNTS individual factors by these; the overall enrichment_confidence
    # stays the final ceiling. Empty {} on legacy/heuristic rows → no discount.
    metric_confidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    # "live" | "parked" | "dead" | "unknown" — explicit website status surfaced
    # to the UI so users can see at a glance when a CSV domain is broken.
    domain_status: Mapped[str] = mapped_column(String(20), default="unknown")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    campaign: Mapped[Campaign] = relationship(back_populates="companies")
    contacts: Mapped[list[Contact]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    linkedin: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification: Mapped[str] = mapped_column(String(20), default="Unknown")
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Durable suppression flag — when True, EVERY send path (outreach draft, real
    # send, auto follow-up, meeting invite) skips this contact. Set on explicit
    # opt-out / "not interested" (Step 05) or manually in Contacts.
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Company] = relationship(back_populates="contacts")


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE")
    )
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    footer: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(20), default="Queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VerifiedContact(Base):
    """Global, cross-tenant directory of verified contacts keyed by company.
    A contact verified once (by any user) is reused by every future campaign for
    the same company, skipping the finder's web search and the paid verify
    credit. Cross-tenant reuse is intentional (standard B2B data tooling)."""
    __tablename__ = "verified_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Normalized website domain — primary match key. "" when the company has none.
    domain_key: Mapped[str] = mapped_column(String(200), default="", index=True)
    # Normalized company name — fallback match key when domain_key == "".
    name_key: Mapped[str] = mapped_column(String(200), default="", index=True)
    company_name: Mapped[str] = mapped_column(String(200), default="")
    contact_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(255))
    linkedin: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("domain_key", "name_key", "email", name="uq_verified_contact"),
    )


class PipelineSnapshot(Base):
    """One-row-per-campaign undo buffer. Captures the campaign's pipeline output
    (company agent-fields + contacts + drafts) before a destructive op; a single
    restore rolls it back and consumes it. Expires after 24h. See the spec."""
    __tablename__ = "pipeline_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    trigger: Mapped[str] = mapped_column(String(40), default="")
    label: Mapped[str] = mapped_column(String(120), default="")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Thread(Base):
    __tablename__ = "threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE")
    )
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String(300), default="")
    # Optional provider conversation id (Gmail threadId) to match an inbound
    # reply to this thread when subject/participant matching is ambiguous.
    provider_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stage: Mapped[str] = mapped_column(String(20), default="Contacted")
    unread: Mapped[bool] = mapped_column(Boolean, default=False)
    last_activity: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Message.sent_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("threads.id", ondelete="CASCADE")
    )
    direction: Mapped[str] = mapped_column(String(8), default="us")  # us | them
    author: Mapped[str] = mapped_column(String(120), default="")
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    is_follow_up: Mapped[bool] = mapped_column(Boolean, default=False)
    # Provider message id (Gmail message `id` / IMAP Message-ID). De-dupe key so
    # re-polling the same mailbox never double-inserts a `them` reply. Indexed.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # AI-classified intent of a `them` reply (interested | meeting_ready |
    # not_interested | question | out_of_office | other). Null on `us` messages
    # and on replies ingested while AI was unavailable.
    intent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    thread: Mapped[Thread] = relationship(back_populates="messages")


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    company: Mapped[str] = mapped_column(String(200))
    contact: Mapped[str] = mapped_column(String(120))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="Upcoming")
    link: Mapped[str] = mapped_column(String(400), default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    campaign: Mapped[Campaign | None] = relationship(back_populates="meetings")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(20))  # Campaign|Email|AI|Verification|User
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="Idle")
    last_run: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RevokedToken(Base):
    """Logout / revocation blocklist. A token's jti lands here on logout;
    get_current_user rejects any token whose jti is present. Rows past
    `expires_at` are purged hourly by the scheduler (the token is dead anyway)."""
    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
