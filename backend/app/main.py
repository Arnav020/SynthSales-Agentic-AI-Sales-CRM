import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.providers.ai import ai
from app.providers.email import email_provider
from app.providers.hunter import hunter
from app.providers.oauth import oauth_provider
from app.providers.search import search
from app.providers.verification import verification
from app.workers.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("synthsales")


def _assert_production_config() -> None:
    """Refuse to boot a non-development environment with insecure defaults."""
    if settings.environment != "development":
        if (
            settings.secret_key in ("", "dev-secret-change-me")
            or len(settings.secret_key) < 32
        ):
            raise RuntimeError(
                "SECRET_KEY must be overridden with a strong value (>=32 chars) "
                "when ENVIRONMENT is not 'development'. "
                'Generate one: python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )


def _run_migrations() -> None:
    """Upgrade the database to the latest Alembic revision (run on boot).

    Builds an Alembic Config with no .ini file so it never reconfigures the
    app's logging; env.py supplies the URL + metadata from app settings/models.
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config as AlembicConfig

    backend_dir = Path(__file__).resolve().parents[1]  # .../backend
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _assert_production_config()

    # Bring the database schema to the latest Alembic revision. Single-worker
    # deploy, so migrating on boot is safe (no multi-worker race): a fresh DB is
    # built from scratch, an existing one gets new revisions, an up-to-date one
    # is a no-op.
    _run_migrations()

    # Runtime admin auto-grant — depends on the ADMIN_EMAILS config (not schema),
    # so it stays here rather than in a migration: promote any matching user.
    from sqlalchemy import text

    if settings.admin_emails_list:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET is_admin=true WHERE LOWER(email) = ANY(:emails)"),
                {"emails": settings.admin_emails_list},
            )

    # Seed demo data (idempotent).
    from app.services.seed import seed_demo

    db = SessionLocal()
    try:
        if settings.environment == "development" or settings.seed_demo_data:
            seed_demo(db)
        else:
            logger.info("Demo seed skipped (environment=%s).", settings.environment)
    except Exception as exc:  # pragma: no cover
        logger.warning("Seed skipped: %s", exc)
    finally:
        db.close()

    start_scheduler()
    yield
    stop_scheduler()


# Interactive API docs are a dev convenience — disabled outside development so a
# production deploy doesn't expose its full schema/try-it surface publicly.
_docs_enabled = settings.environment == "development"

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="AI-Powered B2B Outreach & Lead Generation API",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from app.api.routers import (  # noqa: E402
    access,
    admin,
    agents,
    auth,
    campaigns,
    companies,
    contact_us,
    contacts,
    conversations,
    dashboard,
    emails,
    logs,
    meetings,
    notifications,
)

for module in (
    auth,
    access,
    admin,
    campaigns,
    companies,
    contacts,
    contact_us,
    emails,
    conversations,
    meetings,
    notifications,
    agents,
    logs,
    dashboard,
):
    app.include_router(module.router)


@app.get("/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "integrations": {
            "ai": ai.available,
            "search": search.status,
            # Free syntax/MX verification always runs; paid layer is optional.
            "email_verification": verification.paid_mode or "free (syntax+MX)",
            "email_finder": "hunter" if hunter.available else "off",
            "email_mode": email_provider.mode,
            "google_oauth": oauth_provider.available,
        },
    }


@app.get("/", tags=["meta"])
def root():
    return {"name": settings.app_name, "docs": "/docs", "health": "/health"}
