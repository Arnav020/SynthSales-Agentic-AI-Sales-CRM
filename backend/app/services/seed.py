"""Idempotent demo seed — mirrors the frontend mock data.

Creates a verified demo user and a populated Apex Cloud campaign so the API
returns realistic data immediately (and matches the Next.js mock screens).

Demo login:  jordan@apexcloud.com  /  password123
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.agents.orchestrator import ensure_agents
from app.core.security import hash_password
from app.models import (
    Campaign,
    Company,
    Contact,
    EmailDraft,
    Log,
    Meeting,
    Message,
    Notification,
    Thread,
    User,
)

DEMO_EMAIL = "jordan@apexcloud.com"


def _dt(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def seed_demo(db: Session) -> None:
    if db.query(User).filter(User.email == DEMO_EMAIL).first():
        return  # already seeded

    user = User(
        name="Jordan Pierce",
        company_name="Apex Cloud",
        email=DEMO_EMAIL,
        hashed_password=hash_password("password123"),
        is_verified=True,
        access_status="approved",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    ensure_agents(db, user.id)

    # ---- Campaigns ----
    apex = Campaign(
        owner_id=user.id,
        name="Apex Cloud — Q2 Enterprise Push",
        product="Apex Cloud Data Platform",
        status="Running",
        tone="consultative",
        top_n=50,
        value_proposition="A single platform to unify and serve operational data in real time",
        industry="Data infrastructure",
        industry_pref="Logistics",
    )
    db.add_all(
        [
            apex,
            Campaign(owner_id=user.id, name="FinTech Mid-Market Expansion", product="LedgerOne Payments API", status="Running", tone="professional", top_n=40),
            Campaign(owner_id=user.id, name="HealthOps Pilot Outreach", product="HealthOps Scheduling Suite", status="Paused", tone="friendly", top_n=30),
            Campaign(owner_id=user.id, name="Retail Analytics — Spring", product="ShelfIQ Analytics", status="Completed", tone="concise", top_n=60),
            Campaign(owner_id=user.id, name="Logistics Net-New (Draft)", product="CargoX Route Optimizer", status="Draft", tone="professional", top_n=50),
        ]
    )
    db.commit()
    db.refresh(apex)

    # ---- Companies for Apex ----
    companies_data = [
        dict(name="Northwind Logistics", domain="northwind.com", industry="Logistics & Supply Chain", size="1,000–5,000", location="Chicago, US", ai_score=94, rank=1, match_level="Strong", status="Approved", active_hiring=True, recent_funding="Series D — $120M (Feb 2026)", research_summary="Mid-large 3PL operator modernizing its data stack after a recent cloud migration; consolidating analytics vendors.", research_points=["Mid-large 3PL operator running national freight and warehousing.", "Recently completed a cloud migration and is modernizing its data stack.", "Consolidating analytics vendors — active evaluation signals.", "Series D — $120M raised (Feb 2026), funding a data-platform buildout.", "Actively hiring for data engineering and analytics roles."], match_explanation="High product fit, strong industry alignment, active hiring for data roles."),
        dict(name="Brightwave Manufacturing", domain="brightwave.io", industry="Industrial Manufacturing", size="500–1,000", location="Austin, US", ai_score=88, rank=2, match_level="Strong", status="Approved", active_hiring=True, research_summary="Smart-factory manufacturer generating large telemetry volumes; emphasizes predictive maintenance.", research_points=["Smart-factory manufacturer with heavily instrumented production lines.", "Generates large telemetry volumes from IoT sensors across plants.", "Prioritizing predictive maintenance and real-time analytics.", "Actively hiring for industrial data and ML roles."], match_explanation="Strong requirement satisfaction around real-time analytics."),
        dict(name="Summit Retail Group", domain="summitretail.com", industry="Retail", size="5,000+", location="Seattle, US", ai_score=79, rank=3, match_level="Good", status="Qualified", active_hiring=False, recent_news="Announced 5% cost-reduction program (Apr 2026)", research_summary="National retail chain with a maturing analytics team; recent cost-optimization program.", research_points=["National retail chain with 5,000+ employees across US stores.", "Analytics team maturing from reporting toward predictive use cases.", "Announced a 5% cost-reduction program (Apr 2026) — budget scrutiny likely."], match_explanation="Good fit but cost-cutting news lowers timing score."),
        dict(name="Vertex Health Systems", domain="vertexhealth.org", industry="Healthcare", size="1,000–5,000", location="Boston, US", ai_score=71, rank=4, match_level="Good", status="Researching", active_hiring=True, research_summary="Regional hospital network with strict compliance requirements.", research_points=["Regional hospital network operating across multiple facilities.", "Strict HIPAA / compliance requirements shape any data tooling.", "Hiring for clinical-data and IT roles."], match_explanation="Moderate fit; compliance overhead reduces requirement satisfaction."),
        dict(name="Orbit Media Holdings", domain="orbitmedia.tv", industry="Media & Entertainment", size="200–500", location="Los Angeles, US", ai_score=52, rank=5, match_level="Weak", status="Excluded", active_hiring=False, recent_news="Reported flat YoY revenue (Q1 2026)", research_summary="Smaller media holding company with limited public modernization signals.", research_points=["Smaller media holding company across TV and digital properties.", "Limited public signals of analytics or modernization investment.", "Reported flat YoY revenue (Q1 2026)."], match_explanation="Low requirement satisfaction; excluded by reviewer."),
    ]
    factor_labels = [
        ("Product fit", 0.30), ("Industry alignment", 0.20), ("Company relevance", 0.15),
        ("Requirement satisfaction", 0.15), ("Market compatibility", 0.10), ("Growth indicators", 0.10),
    ]
    companies: list[Company] = []
    for cd in companies_data:
        factors = [
            {"label": lbl, "weight": w, "score": max(40, min(99, cd["ai_score"] + (i - 2) * 3))}
            for i, (lbl, w) in enumerate(factor_labels)
        ]
        co = Company(campaign_id=apex.id, score_factors=factors, **cd)
        db.add(co)
        companies.append(co)
    db.commit()
    for co in companies:
        db.refresh(co)
    northwind, brightwave = companies[0], companies[1]

    # ---- Contacts ----
    contacts_data = [
        (northwind, "Dana Whitfield", "VP of Data & Analytics", "dana.whitfield@northwind.com", "Verified", 96, True),
        (northwind, "Marcus Lee", "Director of Engineering", "m.lee@northwind.com", "Verified", 91, True),
        (northwind, "Priya Nair", "Head of Operations", "priya.nair@northwind.com", "Risky", 64, None),
        (brightwave, "Tom Schaefer", "CTO", "tom@brightwave.io", "Verified", 93, None),
        (brightwave, "Elena Cortez", "VP Operations", "e.cortez@brightwave.io", "Verified", 89, None),
        (companies[2], "Greg Hollis", "Director of Analytics", "greg.hollis@summitretail.com", "Unknown", 41, None),
    ]
    contacts: list[Contact] = []
    for co, name, role, email, verif, conf, approved in contacts_data:
        ct = Contact(company_id=co.id, name=name, role=role, email=email, verification=verif, confidence=conf, approved=approved, linkedin=f"linkedin.com/in/{name.lower().replace(' ', '')}")
        db.add(ct)
        contacts.append(ct)
    db.commit()
    for ct in contacts:
        db.refresh(ct)
    dana, tom = contacts[0], contacts[3]

    # ---- Email drafts ----
    footer = "Best,\nJordan Pierce\nAccount Executive, Apex Cloud\njordan@apexcloud.com"
    db.add_all(
        [
            EmailDraft(contact_id=dana.id, state="Sent", footer=footer,
                       subject="Unifying Northwind's analytics stack after the cloud migration",
                       body="Hi Dana,\n\nCongratulations on Northwind's recent cloud migration. As you consolidate analytics vendors, Apex Cloud gives data teams a single platform to model ops data and serve it in real time.\n\nWould a 20-minute walkthrough next week be useful?"),
            EmailDraft(contact_id=tom.id, state="Queued", footer=footer,
                       subject="Predictive maintenance telemetry — one platform for Brightwave",
                       body="Hi Tom,\n\nYour smart-factory push generates exactly the kind of high-volume telemetry that's painful to operationalize. Apex Cloud unifies it so your models get fresh, reliable inputs.\n\nOpen to a short technical demo this week?"),
        ]
    )

    # ---- Conversation thread (Dana replied) ----
    thread = Thread(campaign_id=apex.id, company_id=northwind.id, contact_id=dana.id,
                    subject="Unifying Northwind's analytics stack after the cloud migration",
                    stage="Replied", unread=True, last_activity=_dt(2026, 5, 27, 9, 12))
    db.add(thread)
    db.flush()
    db.add_all(
        [
            Message(thread_id=thread.id, direction="us", author="Jordan Pierce", sent_at=_dt(2026, 5, 22, 10, 0),
                    subject="Unifying Northwind's analytics stack after the cloud migration",
                    body="Hi Dana, congratulations on Northwind's recent cloud migration... Would a 20-minute walkthrough next week be useful?"),
            Message(thread_id=thread.id, direction="them", author="Dana Whitfield", sent_at=_dt(2026, 5, 27, 9, 12),
                    body="Hi Jordan — timely. We're actively evaluating platforms this quarter. Can you send availability for Thursday or Friday?"),
        ]
    )

    # ---- Meetings ----
    db.add_all(
        [
            Meeting(campaign_id=apex.id, company="Cedar Clinics", contact="Dr. Amelia Ross", scheduled_at=_dt(2026, 5, 29, 19, 0), status="Upcoming", link="https://meet.example.com/cedar-apex", notes="Focus on scheduling no-show reduction."),
            Meeting(campaign_id=apex.id, company="Northwind Logistics", contact="Dana Whitfield", scheduled_at=_dt(2026, 5, 30, 19, 0), status="Upcoming", link="https://meet.example.com/northwind-apex", notes="Tailor to route + warehouse data."),
            Meeting(campaign_id=apex.id, company="Summit Retail Group", contact="Greg Hollis", scheduled_at=_dt(2026, 5, 19, 17, 30), status="Completed", link="https://meet.example.com/summit", notes="Budget frozen until Q3."),
        ]
    )

    # ---- Notifications ----
    db.add_all(
        [
            Notification(owner_id=user.id, type="reply", title="New reply from Dana Whitfield", detail="Northwind Logistics — asking for meeting availability.", read=False),
            Notification(owner_id=user.id, type="meeting", title="Meeting scheduled", detail="Cedar Clinics — May 29, 3:00 PM ET.", read=False),
            Notification(owner_id=user.id, type="followup", title="Follow-up sent automatically", detail="Brightwave — Tom Schaefer (no reply after 24h).", read=True),
            Notification(owner_id=user.id, type="verification", title="Email verification failed", detail="Greg Hollis (Summit Retail) returned status: Unknown.", read=True),
        ]
    )

    # ---- Logs ----
    db.add_all(
        [
            Log(owner_id=user.id, category="Email", level="info", message="Reply detected from dana.whitfield@northwind.com."),
            Log(owner_id=user.id, category="AI", level="info", message="Scoring agent ranked 5 companies for Apex Cloud."),
            Log(owner_id=user.id, category="Verification", level="warn", message="Verifalia: greg.hollis@summitretail.com → Unknown."),
            Log(owner_id=user.id, category="Campaign", level="info", message="Enrichment completed for Apex Cloud."),
        ]
    )
    db.commit()
