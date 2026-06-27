from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_name: str = "SynthSales API"
    environment: str = "development"
    # In production (environment != "development") the demo user is NOT seeded.
    # Set true to force the demo seed in a non-dev environment (e.g. a staging demo).
    seed_demo_data: bool = False
    cors_origins: str = "http://localhost:3000"
    # Where the public contact form delivers (marketing site "contact us").
    contact_inbox: str = "brodomyjob@gmail.com"

    # Security
    secret_key: str = "dev-secret-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 days

    # Database
    database_url: str = (
        "postgresql+psycopg://synthsales:synthsales_dev_pw@localhost:5433/synthsales"
    )

    # Abuse-control rate limiter (core/ratelimit.py). Leave `redis_url` blank to
    # use the in-memory limiter (correct at single-worker; resets on restart).
    # Set it to a Redis URL (e.g. redis://host:6379/0) to share buckets across
    # workers/instances — required for a correct multi-worker deploy. `trust_proxy`
    # makes the auth limiter key on the X-Forwarded-For client IP instead of the
    # direct peer; turn it ON only when a trusted reverse proxy fronts the app
    # (every PaaS does), OFF in local dev where XFF is attacker-controlled.
    redis_url: str = ""
    trust_proxy: bool = False

    # AI provider selection.
    # `ai_providers` is a comma-separated priority list with automatic failover
    # on rate-limit errors, e.g. "gemini,groq,openrouter". If left blank,
    # `ai_provider` picks a single backend; "auto" prefers any with a key
    # (gemini → groq → openrouter).
    ai_providers: str = ""
    ai_provider: str = "auto"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"

    # Web search. The free DuckDuckGo scraper (`ddgs`) needs no key but gets
    # rate-limited from datacenter IPs, so for deployment configure Serper.io
    # (real Google results). `serper_api_keys` is a comma-separated pool drained
    # ONE key at a time (a key is used until it returns "out of credits", then
    # the next takes over). `search_order` sets which backend is tried first; the
    # ddgs→serper default uses the free scraper locally and falls through to
    # Serper when ddgs is blocked (a circuit breaker stops retrying a dead ddgs).
    serper_api_keys: str = ""
    search_order: str = "ddgs,serper"

    # Email verification (paid layer — optional; the free MX/syntax layer always runs).
    # Verifalia is preferred when configured (more credits); ZeroBounce is the fallback.
    zerobounce_api_key: str = ""
    verifalia_username: str = ""
    verifalia_password: str = ""
    # Hunter.io email finder — one lookup per company resolves the top contact +
    # the company's real mail domain (free tier is small, so it's used sparingly).
    hunter_api_key: str = ""

    # Email
    gmail_credentials_file: str = ""
    gmail_token_file: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "SynthSales <no-reply@synthsales.example>"
    # Transactional email APIs over HTTPS. Cloud hosts (Render's free tier, etc.)
    # block outbound SMTP ports, so prefer an HTTP provider on deploy. Resend takes
    # precedence over Brevo when both are set; the From address is taken from
    # `smtp_from` and must be verified with the active provider.
    resend_api_key: str = ""
    brevo_api_key: str = ""
    # Gmail API send over HTTPS from one operator-owned Gmail account. Use this
    # when you want the app's transactional/outbound mail to come from Gmail on a
    # cloud host where SMTP is unreliable. If send-specific client id/secret are
    # blank, the Google OAuth client settings below are reused.
    gmail_send_client_id: str = ""
    gmail_send_client_secret: str = ""
    gmail_send_refresh_token: str = ""

    # Google OAuth (sign-in / sign-up). Optional: leave the id/secret blank to
    # disable — the "Continue with Google" button hides and the OAuth routes
    # 404. `frontend_url` is where the backend redirects the SPA after a
    # successful callback.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8000/api/auth/google/callback"
    # Per-user Google Calendar connection (offline consent for calendar.events).
    # Register this URI in the OAuth client's "Authorized redirect URIs".
    google_calendar_redirect_uri: str = "http://127.0.0.1:8000/api/auth/google/calendar/callback"
    # Per-user Gmail read connection (offline consent for gmail.readonly). Register
    # this URI in the OAuth client's "Authorized redirect URIs".
    google_mailbox_redirect_uri: str = "http://127.0.0.1:8000/api/auth/google/mailbox/callback"
    frontend_url: str = "http://localhost:3000"

    # Automation
    # Scheduler POLL cadence — how often the worker wakes to check threads.
    followup_interval_minutes: int = 15
    enable_scheduler: bool = True
    # How often the inbound poller wakes to read each connected mailbox for new
    # replies. Independent of the follow-up cadence above.
    inbound_poll_minutes: int = 5
    # Minimum AI confidence (0-100) required before a "not_interested" reply is
    # allowed to opt the contact out + close the thread. Below this, the reply is
    # only surfaced — never auto-opted-out.
    reply_optout_min_confidence: int = 70
    # How long a thread must sit unanswered (OUR last message) before an automatic
    # follow-up nudge fires. Decoupled from the poll cadence above, so you can poll
    # often but only nudge after, e.g., 10 days.
    followup_delay_days: int = 7
    # Max automatic follow-up nudges per thread before it auto-stalls.
    max_follow_ups: int = 3
    # Default generated-meeting length (minutes) for the calendar event end time.
    meeting_default_duration_minutes: int = 30
    # IMAP fallback (single global mailbox) for inbound reading when no per-user
    # Gmail token is connected — dev/testing convenience. Blank ⇒ disabled.
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""

    # Comma-separated list of emails that should be auto-granted the admin
    # role. Applied at startup (sweeps existing users) and when a new user
    # finishes email verification. Case-insensitive.
    admin_emails: str = ""

    @field_validator("database_url")
    @classmethod
    def _normalize_db_driver(cls, v: str) -> str:
        """Force SQLAlchemy onto the installed psycopg (v3) driver.

        Managed-Postgres providers (Render, Railway, Heroku, …) hand out URLs
        with a bare ``postgresql://`` (or legacy ``postgres://``) scheme, which
        SQLAlchemy resolves to psycopg2 — a driver we don't ship. Rewrite both to
        ``postgresql+psycopg://`` so the platform's connection string works
        verbatim with no manual editing. URLs that already name a driver
        (``postgresql+psycopg``, ``+asyncpg``, …) are left untouched.
        """
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ai_providers_list(self) -> list[str]:
        return [p.strip().lower() for p in self.ai_providers.split(",") if p.strip()]

    @property
    def serper_api_keys_list(self) -> list[str]:
        return [k.strip() for k in self.serper_api_keys.split(",") if k.strip()]

    @property
    def search_order_list(self) -> list[str]:
        return [s.strip().lower() for s in self.search_order.split(",") if s.strip()]

    @property
    def admin_emails_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
