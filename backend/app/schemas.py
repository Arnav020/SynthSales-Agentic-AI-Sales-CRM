"""Pydantic request/response schemas."""
from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# Password policy: long enough to resist guessing, capped so a multi-kilobyte
# string can't waste pbkdf2 CPU, and at least two character classes so trivial
# passwords ("password", "12345678") are rejected without forcing every class.
_PW_MIN, _PW_MAX = 8, 128
_PW_CLASSES = (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")


def _validate_password_strength(value: str) -> str:
    if len(value) < _PW_MIN:
        raise ValueError(f"Password must be at least {_PW_MIN} characters.")
    if len(value) > _PW_MAX:
        raise ValueError(f"Password must be at most {_PW_MAX} characters.")
    if sum(bool(re.search(p, value)) for p in _PW_CLASSES) < 2:
        raise ValueError(
            "Password must include at least two of: lowercase, uppercase, "
            "number, symbol."
        )
    return value


# ---------- Auth ----------
class RegisterIn(BaseModel):
    name: str
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class VerifyOtpIn(BaseModel):
    email: EmailStr
    code: str


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    email: EmailStr
    code: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: int
    name: str
    company_name: str = ""
    email: EmailStr
    is_verified: bool
    is_admin: bool = False
    outbound_enabled: bool = False
    autonomous_replies: bool = False
    calendar_connected: bool = False
    mailbox_connected: bool = False
    access_status: str = "none"
    access_review_note: str | None = None
    created_at: datetime


class UserUpdate(BaseModel):
    name: str | None = None
    # Unlike name, an empty string is legal: it clears the company so prompts
    # revert to the anonymous "we".
    company_name: str | None = None
    outbound_enabled: bool | None = None
    autonomous_replies: bool | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Name can't be empty")
        if len(v) > 120:
            raise ValueError("Name is too long (max 120 characters)")
        return v

    @field_validator("company_name")
    @classmethod
    def _clean_company(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 200:
            raise ValueError("Company name is too long (max 200 characters)")
        return v


class RegisterOut(UserOut):
    # In development, when email isn't actually delivered, surface the OTP so
    # the user can still verify. Always null in production / when email is sent.
    dev_otp: str | None = None
    email_sent: bool = False


class AccessRequestIn(BaseModel):
    note: str | None = None

    @field_validator("note")
    @classmethod
    def _trim(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        return v[:1000] or None


# ---------- Campaign ----------
class CampaignBase(BaseModel):
    name: str
    product: str = ""
    tone: str = "professional"
    top_n: int = 50
    product_description: str = ""
    value_proposition: str = ""
    industry: str = ""
    differentiators: str = ""
    icp: str = ""
    industry_pref: str = ""
    geography: str = ""
    company_size: str = ""
    business_requirements: str = ""
    ranking_criteria: str = ""
    email_template: str = ""
    footer: str = ""
    personalization_level: int = 2


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: str | None = None
    product: str | None = None
    status: str | None = None
    tone: str | None = None
    top_n: int | None = None
    email_template: str | None = None
    footer: str | None = None
    personalization_level: int | None = None


class CampaignOut(ORMModel):
    id: int
    name: str
    product: str
    status: str
    tone: str
    top_n: int
    created_at: datetime
    # rollups
    companies_uploaded: int = 0
    companies_researched: int = 0
    emails_sent: int = 0
    replies_received: int = 0
    meetings_booked: int = 0


class PipelineAgentOut(BaseModel):
    key: str
    name: str
    description: str
    order: int
    status: str        # Idle | Running | Error  (from AgentConfig — per-user)
    enabled: bool      # whether the agent is enabled at all (per-user toggle)
    last_run: datetime | None = None
    total: int = 0     # work items applicable to this campaign (e.g. companies)
    completed: int = 0 # how many of those are done
    runnable: bool = True  # False for "meeting" (no on-demand run)


class SnapshotStatusOut(BaseModel):
    available: bool
    reason: str | None = None
    trigger: str | None = None
    label: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None


# ---------- Company / Contact ----------
class ScoreFactor(BaseModel):
    label: str
    weight: float
    score: int


class ContactOut(ORMModel):
    id: int
    company_id: int
    name: str
    role: str
    email: str
    linkedin: str | None = None
    verification: str
    confidence: int
    approved: bool | None = None
    do_not_contact: bool = False


class ContactUpdate(BaseModel):
    email: str | None = None
    approved: bool | None = None
    role: str | None = None
    name: str | None = None
    do_not_contact: bool | None = None


class ContactCreate(BaseModel):
    name: str
    role: str = ""
    email: str = ""
    linkedin: str | None = None

    @field_validator("name")
    @classmethod
    def _name_required(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("Contact name is required.")
        return v.strip()


class CompanyOut(ORMModel):
    id: int
    campaign_id: int
    name: str
    domain: str
    mail_domain: str = ""
    industry: str
    size: str
    location: str
    ai_score: int
    rank: int
    match_level: str
    status: str
    research_summary: str
    # 5–8 bullet research profile. metric_confidence is intentionally NOT here —
    # it's a backend-only scoring signal and must never reach the client.
    research_points: list[str] = []
    match_explanation: str
    score_factors: list = []
    recent_funding: str | None = None
    recent_news: str | None = None
    active_hiring: bool
    enrichment_confidence: int = 50
    domain_status: str = "unknown"
    contacts_found: int = 0
    contacts_verified: int = 0


class CompanyDetailOut(CompanyOut):
    contacts: list[ContactOut] = []


class CompanyStatusUpdate(BaseModel):
    status: str  # Approved | Excluded | ...


class CompanyMailDomainUpdate(BaseModel):
    mail_domain: str = ""


# ---------- Email drafts ----------
class EmailDraftOut(ORMModel):
    id: int
    contact_id: int
    subject: str
    body: str
    footer: str
    state: str


class EmailDraftUpdate(BaseModel):
    subject: str | None = None
    body: str | None = None
    footer: str | None = None
    state: str | None = None


# ---------- Threads / messages ----------
class MessageOut(ORMModel):
    id: int
    direction: str
    author: str
    subject: str | None = None
    body: str
    is_follow_up: bool
    intent: str | None = None
    sent_at: datetime


class ThreadOut(ORMModel):
    id: int
    campaign_id: int
    company_id: int | None = None
    contact_id: int | None = None
    subject: str
    stage: str
    unread: bool
    last_activity: datetime
    company_name: str = ""
    contact_name: str = ""
    role: str = ""
    email: str = ""
    # Intent of the most recent inbound (`them`) message, for the thread badge.
    last_intent: str | None = None


class ThreadDetailOut(ThreadOut):
    messages: list[MessageOut] = []
    ai_suggestion: str | None = None


class ReplyIn(BaseModel):
    body: str


# ---------- Meetings ----------
class MeetingOut(ORMModel):
    id: int
    campaign_id: int | None = None
    company: str
    contact: str
    scheduled_at: datetime
    status: str
    link: str
    notes: str | None = None


# ---------- Notifications ----------
class NotificationOut(ORMModel):
    id: int
    type: str
    title: str
    detail: str
    read: bool
    created_at: datetime


# ---------- Logs ----------
class LogOut(ORMModel):
    id: int
    category: str
    level: str
    message: str
    created_at: datetime


# ---------- Agents ----------
class AgentOut(ORMModel):
    id: int
    key: str
    name: str
    description: str
    enabled: bool
    order: int
    status: str
    last_run: datetime | None = None


class AgentUpdate(BaseModel):
    enabled: bool


# ---------- Dashboard ----------
class FunnelStage(BaseModel):
    label: str
    value: int


class DashboardOut(BaseModel):
    active_campaigns: int
    paused_campaigns: int
    completed_campaigns: int
    companies_uploaded: int
    companies_researched: int
    emails_sent: int
    replies_received: int
    meetings_booked: int
    funnel: list[FunnelStage]
