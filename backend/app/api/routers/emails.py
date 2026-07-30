from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.outreach import nudge_missing_company, outreach_agent
from app.api.deps import get_current_user
from app.api.pagination import Page, paginate
from app.core.database import get_db
from app.models import Campaign, Company, Contact, EmailDraft, User
from app.providers.email import email_provider
from app.schemas import EmailDraftOut, EmailDraftUpdate
from app.services.events import add_log

router = APIRouter(prefix="/api/emails", tags=["emails"])


def _owned_draft(db: Session, user: User, draft_id: int) -> EmailDraft:
    d = db.get(EmailDraft, draft_id)
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")
    contact = db.get(Contact, d.contact_id)
    if not contact or contact.company.campaign.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Draft not found")
    return d


@router.get("", response_model=list[EmailDraftOut])
def list_drafts(
    campaign_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: Page = Depends(),
):
    q = (
        db.query(EmailDraft)
        .join(Contact, Contact.id == EmailDraft.contact_id)
        .join(Company, Company.id == Contact.company_id)
        .join(Campaign, Campaign.id == Company.campaign_id)
        .filter(Campaign.owner_id == user.id)
    )
    if campaign_id is not None:
        q = q.filter(Campaign.id == campaign_id)
    return paginate(q, page).all()


@router.patch("/{draft_id}", response_model=EmailDraftOut)
def update_draft(
    draft_id: int,
    payload: EmailDraftUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = _owned_draft(db, user, draft_id)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(d, k, v)
    db.commit()
    db.refresh(d)
    return d


@router.post("/{draft_id}/regenerate", response_model=EmailDraftOut)
def regenerate(
    draft_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    d = _owned_draft(db, user, draft_id)
    contact = db.get(Contact, d.contact_id)
    company = contact.company
    campaign = company.campaign
    nudge_missing_company(db, user.id)
    subject, body = outreach_agent._generate(
        contact, company, campaign, sender=(user.company_name or "").strip()
    )
    d.subject, d.body = subject, body
    db.commit()
    db.refresh(d)
    add_log(db, user.id, "AI", f"Regenerated draft for {contact.name}.")
    return d


@router.post("/{draft_id}/test")
def send_test(
    draft_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    d = _owned_draft(db, user, draft_id)
    email_provider.send(user.email, f"[TEST] {d.subject}", f"{d.body}\n\n{d.footer}")
    return {"detail": f"Test email sent to {user.email}", "mode": email_provider.mode}
