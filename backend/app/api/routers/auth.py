import random
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.agents.orchestrator import ensure_agents
from app.api.deps import get_current_user, oauth2_scheme
from app.core.database import get_db
from app.core.ratelimit import client_ip, limiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models import RevokedToken, User, utcnow
from app.core.config import settings
from app.providers.email import email_provider
from app.providers.email_templates import otp_email
from app.providers.oauth import oauth_provider
from app.schemas import (
    ForgotPasswordIn,
    LoginIn,
    RegisterIn,
    RegisterOut,
    ResetPasswordIn,
    Token,
    UserOut,
    UserUpdate,
    VerifyOtpIn,
)
from app.services.events import add_log

router = APIRouter(prefix="/api/auth", tags=["auth"])

# --- Abuse controls -------------------------------------------------------
# OTP brute-force lockout + per-IP/per-email throttles. State is in-memory (see
# core/ratelimit.py: per-process, resets on restart). The messages below surface
# verbatim in the UI, so keep them human-readable.
MAX_OTP_ATTEMPTS = 5
_RL_WINDOW = 600  # seconds (10 minutes)
THROTTLE_MSG = "Too many sign-up attempts. Please wait a few minutes and try again."
RESEND_THROTTLE_MSG = (
    "Too many code requests. Please wait a few minutes before requesting another code."
)
RESET_THROTTLE_MSG = (
    "Too many reset requests. Please wait a few minutes before trying again."
)
OTP_LOCKED_MSG = "Too many incorrect codes. Request a new code to continue."


def _new_otp() -> str:
    return f"{random.randint(0, 999999):06d}"


def _send_otp(email: str, otp: str, purpose: str = "verify") -> bool:
    """Email the OTP (branded HTML + plain-text fallback). Returns True only
    when actually delivered to a real inbox (via SMTP/Gmail/Brevo/Resend) — console mode
    counts as not delivered."""
    stamp = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
    subject, body, html = otp_email(otp, stamp, purpose)
    sent = email_provider.send(email, subject, body, html)
    return sent and email_provider.mode in ("smtp", "gmail", "brevo", "resend")


def _dev_otp(otp: str, delivered: bool) -> str | None:
    """Expose the OTP only in development when it wasn't actually emailed."""
    if settings.environment == "development" and (
        not delivered or email_provider.mode == "console"
    ):
        return otp
    return None


def _consume_otp(db: Session, email: str, code: str, prefix: str, lock_label: str) -> User:
    """Shared OTP validation ladder for verify-otp and reset-password (they had
    drifted once before being unified here). Mirrors the prior inline ladders exactly:
    an unknown email / no active code reads identically to a wrong code (anti-enumeration);
    expiry self-heals (400 — request a new one); MAX_OTP_ATTEMPTS triggers a logged 429
    lock; a mismatch increments + commits the attempt counter. On success the OTP is
    cleared and the counter reset, and the user is returned for the caller to apply its
    channel-specific action and commit. `prefix` is the channel tag ('V'|'R'); `lock_label`
    is the audit-log context."""
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.otp_code:
        raise HTTPException(status_code=400, detail="Invalid code")
    # Expiry is checked before the lock so an expired code self-heals: the user
    # is routed to request a new one (resend resets the attempt counter).
    if user.otp_expires_at and user.otp_expires_at < utcnow():
        raise HTTPException(status_code=400, detail="Code expired. Request a new code.")
    if user.otp_attempts >= MAX_OTP_ATTEMPTS:
        add_log(
            db, user.id, "User",
            f"{lock_label} locked for {user.email} (too many attempts).",
            level="warn",
        )
        raise HTTPException(status_code=429, detail=OTP_LOCKED_MSG)
    if not secrets.compare_digest(user.otp_code.encode(), (prefix + code).encode()):
        user.otp_attempts += 1
        db.commit()
        if user.otp_attempts >= MAX_OTP_ATTEMPTS:
            add_log(
                db, user.id, "User",
                f"{lock_label} locked for {user.email} (too many attempts).",
                level="warn",
            )
            raise HTTPException(status_code=429, detail=OTP_LOCKED_MSG)
        raise HTTPException(status_code=400, detail="Invalid code")
    user.otp_code = None
    user.otp_attempts = 0
    return user


@router.post("/register", response_model=RegisterOut, status_code=201)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if not limiter.check(f"register:ip:{ip}", 5, _RL_WINDOW) or not limiter.check(
        f"register:email:{payload.email.lower()}", 3, _RL_WINDOW
    ):
        add_log(
            db, None, "User",
            f"Registration throttled for {payload.email} from {ip}.",
            level="warn",
        )
        raise HTTPException(status_code=429, detail=THROTTLE_MSG)
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    otp = _new_otp()
    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        is_verified=False,
        otp_code="V" + otp,  # provenance tag: signup-verification channel
        otp_expires_at=utcnow() + timedelta(minutes=15),
        otp_attempts=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    ensure_agents(db, user.id)
    delivered = _send_otp(user.email, otp)
    add_log(
        db, user.id, "User",
        f"Registered {user.email}; OTP {'emailed' if delivered else 'issued (not emailed)'}.",
    )
    out = RegisterOut.model_validate(user)
    out.email_sent = delivered
    out.dev_otp = _dev_otp(otp, delivered)
    return out


@router.post("/verify-otp", response_model=Token)
def verify_otp(payload: VerifyOtpIn, db: Session = Depends(get_db)):
    # Only signup-verification codes ("V" prefix) are accepted here: a code issued
    # by forgot-password can't flip is_verified (or reach the admin auto-grant).
    user = _consume_otp(db, payload.email, payload.code, "V", "OTP verification")
    user.is_verified = True
    # Auto-grant admin if this email is in the configured admin list.
    if user.email.lower() in settings.admin_emails_list:
        user.is_admin = True
    db.commit()
    return Token(access_token=create_access_token(str(user.id)))


@router.post("/resend-otp")
def resend_otp(
    request: Request,
    payload: LoginIn | None = None,
    email: str = "",
    db: Session = Depends(get_db),
):
    target = (email or (payload.email if payload else "")).strip()
    ip = client_ip(request)
    # Throttle before the DB lookup: this both blunts email enumeration and caps
    # how many real OTP emails a single inbox can be made to receive.
    if not limiter.check(f"resend:ip:{ip}", 5, _RL_WINDOW) or not limiter.check(
        f"resend:email:{target.lower()}", 3, _RL_WINDOW
    ):
        add_log(
            db, None, "User",
            f"Resend-OTP throttled for {target or '(blank)'} from {ip}.",
            level="warn",
        )
        raise HTTPException(status_code=429, detail=RESEND_THROTTLE_MSG)
    user = db.query(User).filter(User.email == target).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    otp = _new_otp()
    user.otp_code = "V" + otp  # provenance tag: signup-verification channel
    user.otp_expires_at = utcnow() + timedelta(minutes=15)
    user.otp_attempts = 0
    db.commit()
    delivered = _send_otp(user.email, otp)
    return {
        "detail": "OTP resent" if delivered else "OTP regenerated (email not configured)",
        "email_sent": delivered,
        "dev_otp": _dev_otp(otp, delivered),
    }


@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)
):
    ip = client_ip(request)
    # Throttle before the lookup. Anti-enumeration: the existence check returns the
    # same generic 200 body whether or not the account exists (the throttle path 429s).
    if not limiter.check(f"reset:ip:{ip}", 5, _RL_WINDOW) or not limiter.check(
        f"reset:email:{payload.email.lower()}", 3, _RL_WINDOW
    ):
        add_log(
            db, None, "User",
            f"Password-reset throttled for {payload.email} from {ip}.",
            level="warn",
        )
        raise HTTPException(status_code=429, detail=RESET_THROTTLE_MSG)
    user = db.query(User).filter(User.email == payload.email).first()
    generic = {"detail": "If that account exists, a reset code was sent."}
    # Outside development, never reveal whether the account exists: always report
    # email_sent=true and withhold dev_otp. (In dev we keep the real values + OTP.)
    is_dev = settings.environment == "development"
    if not user:
        return {**generic, "email_sent": False if is_dev else True, "dev_otp": None}
    otp = _new_otp()
    user.otp_code = "R" + otp  # provenance tag: password-reset channel
    user.otp_expires_at = utcnow() + timedelta(minutes=15)
    user.otp_attempts = 0
    db.commit()
    delivered = _send_otp(user.email, otp, purpose="reset")
    add_log(db, user.id, "User", f"Password-reset code issued for {user.email}.")
    return {
        **generic,
        "email_sent": delivered if is_dev else True,
        "dev_otp": _dev_otp(otp, delivered),  # already None outside dev
    }


@router.post("/reset-password")
def reset_password(payload: ResetPasswordIn, db: Session = Depends(get_db)):
    # Only password-reset codes ("R" prefix) are accepted here: a signup code
    # can't be replayed to change the password.
    user = _consume_otp(db, payload.email, payload.code, "R", "Password-reset")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    add_log(db, user.id, "User", f"Password reset for {user.email}.")
    return {"detail": "Password updated. You can sign in now."}


@router.post("/login", response_model=Token)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_verified:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email before signing in. Check your inbox for the code.",
        )
    return Token(access_token=create_access_token(str(user.id)))


@router.post("/token", response_model=Token, include_in_schema=True)
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """OAuth2 password flow — lets Swagger's Authorize button work."""
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    return Token(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.name is not None:
        user.name = payload.name  # stripped + length-checked by UserUpdate
        add_log(db, user.id, "User", f"Display name updated to '{user.name}'.")
    if payload.company_name is not None:
        user.company_name = payload.company_name  # stripped; "" clears it
        add_log(
            db, user.id, "User",
            f"Company name updated to '{user.company_name}'." if user.company_name
            else "Company name cleared.",
        )
    if payload.outbound_enabled is not None:
        if payload.outbound_enabled and not user.has_access:
            raise HTTPException(
                status_code=403,
                detail="Request access before turning on outbound sending.",
            )
        user.outbound_enabled = payload.outbound_enabled
        add_log(
            db,
            user.id,
            "User",
            f"Outbound email sending {'ENABLED' if payload.outbound_enabled else 'PAUSED'}.",
        )
    if payload.autonomous_replies is not None:
        user.autonomous_replies = payload.autonomous_replies
        add_log(
            db,
            user.id,
            "User",
            f"Autonomous replies {'ENABLED' if payload.autonomous_replies else 'DISABLED'}.",
        )
    db.commit()
    db.refresh(user)
    return user


@router.post("/logout", status_code=204)
def logout(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Revoke the presented token (server-side logout). Idempotent — re-logging
    out the same token is a no-op."""
    payload = decode_token(token) or {}
    jti = payload.get("jti")
    if jti and not db.query(RevokedToken.id).filter(RevokedToken.jti == jti).first():
        exp = payload.get("exp")
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc) if exp else utcnow()
        db.add(RevokedToken(jti=jti, user_id=user.id, expires_at=expires_at))
        db.commit()
    add_log(db, user.id, "User", "Signed out.")


# --- Google OAuth ---------------------------------------------------------
# Authorization Code flow. The SPA sends the browser to /google/start, which
# redirects to Google; Google redirects back to /google/callback, which mints
# our JWT and redirects to the frontend /oauth-callback page. Everything 404s /
# stays hidden when Google credentials aren't configured.


@router.get("/providers")
def auth_providers():
    """Which social-login providers are configured — drives the auth-page UI."""
    return {"google": oauth_provider.available}


def _oauth_error_redirect(reason: str) -> RedirectResponse:
    # Send failures back to the SPA (never raw JSON in the browser) so the
    # callback page can show friendly copy.
    return RedirectResponse(
        f"{settings.frontend_url}/oauth-callback?error={reason}", status_code=307
    )


@router.get("/google/start")
def google_start():
    if not oauth_provider.available:
        raise HTTPException(status_code=404, detail="Google sign-in is not enabled")
    # CSRF via double-submit cookie: the state echoed back by Google must match
    # the one in this cookie (no server-side session store exists).
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(oauth_provider.authorization_url(state), status_code=307)
    resp.set_cookie(
        "oauth_state",
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        path="/api/auth",
    )
    return resp


@router.get("/google/callback")
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    if not oauth_provider.available:
        raise HTTPException(status_code=404, detail="Google sign-in is not enabled")
    if error:  # user denied consent at Google
        return _oauth_error_redirect("denied")
    if not state or state != request.cookies.get("oauth_state"):
        return _oauth_error_redirect("state")
    if not code:
        return _oauth_error_redirect("missing_code")

    tokens = oauth_provider.exchange_code(code)
    if not tokens or not tokens.get("access_token"):
        return _oauth_error_redirect("exchange")
    info = oauth_provider.fetch_userinfo(tokens["access_token"])
    if not info:
        return _oauth_error_redirect("userinfo")

    sub = info.get("sub")
    email = (info.get("email") or "").lower()
    name = info.get("name") or email
    if not sub or not email:
        return _oauth_error_redirect("userinfo")
    # Never trust an unverified Google email — it could be someone else's.
    if not info.get("email_verified"):
        return _oauth_error_redirect("unverified_google")

    # Resolve the account: by Google sub, else by email (link onto the existing
    # password account), else create a fresh verified user.
    user = db.query(User).filter(User.google_sub == sub).first()
    is_new = False
    if not user:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.google_sub = sub
            user.is_verified = True
        else:
            user = User(
                name=name,
                email=email,
                # Google verified the email; there's no password login path, so
                # store a random unguessable hash to satisfy the non-null column.
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                is_verified=True,
                google_sub=sub,
            )
            db.add(user)
            is_new = True
    # Admin auto-grant, mirroring verify-otp.
    if user.email.lower() in settings.admin_emails_list:
        user.is_admin = True
    db.commit()
    db.refresh(user)
    if is_new:
        ensure_agents(db, user.id)
    add_log(db, user.id, "User", f"Signed in with Google ({user.email}).")

    token = create_access_token(str(user.id))
    resp = RedirectResponse(
        f"{settings.frontend_url}/oauth-callback?token={token}", status_code=307
    )
    resp.delete_cookie("oauth_state", path="/api/auth")
    return resp


# --- Google Calendar connection (per-user, incremental consent) ------------
# Reuses the OAuth client to request offline access for the calendar.events
# scope so booking can create a real Meet event on THIS user's calendar. The
# connect endpoint is authenticated and returns the consent URL as JSON for the
# SPA to navigate to; the callback is a public browser redirect whose `state` is
# a short-lived signed JWT binding the grant back to the logged-in user.


@router.get("/google/calendar/connect")
def google_calendar_connect(user: User = Depends(get_current_user)):
    if not oauth_provider.available:
        raise HTTPException(status_code=404, detail="Google integration is not enabled")
    # Signed, short-lived state both identifies the user on callback and acts as an
    # unforgeable CSRF token (HMAC over our secret_key). No cookie is used: the SPA
    # fetches this URL with its bearer token, then navigates the browser to it (a
    # cross-origin fetch can't persist a Set-Cookie anyway).
    state = create_access_token(str(user.id), expires_minutes=10)
    return {"url": oauth_provider.calendar_authorization_url(state)}


@router.get("/google/calendar/callback")
def google_calendar_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    base = f"{settings.frontend_url}/settings?calendar="
    if not oauth_provider.available:
        raise HTTPException(status_code=404, detail="Google integration is not enabled")
    if error:
        return RedirectResponse(base + "denied", status_code=307)
    # Verify the signed state (signature + expiry) and recover the user id.
    user_id = decode_access_token(state) if state else None
    if not user_id or not code:
        return RedirectResponse(base + "state", status_code=307)
    tokens = oauth_provider.exchange_code(
        code, redirect_uri=settings.google_calendar_redirect_uri
    )
    refresh_token = (tokens or {}).get("refresh_token")
    if not refresh_token:
        # No refresh token ⇒ offline access wasn't granted; ask the user to retry.
        return RedirectResponse(base + "exchange", status_code=307)
    user = db.get(User, int(user_id))
    if not user:
        return RedirectResponse(base + "state", status_code=307)
    user.google_calendar_token = refresh_token
    db.commit()
    add_log(db, user.id, "User", "Connected Google Calendar.")
    return RedirectResponse(base + "connected", status_code=307)


@router.post("/google/calendar/disconnect", response_model=UserOut)
def google_calendar_disconnect(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    user.google_calendar_token = None
    db.commit()
    db.refresh(user)
    add_log(db, user.id, "User", "Disconnected Google Calendar.")
    return user


# --- Google Mailbox connection (per-user, gmail.readonly) ------------------
# Mirrors the calendar grant exactly: connect returns the consent URL as JSON
# (the SPA navigates to it with its bearer token), the callback is a public
# browser redirect whose `state` is a short-lived signed JWT binding the grant
# back to the logged-in user, and disconnect clears the stored token.


@router.get("/google/mailbox/connect")
def google_mailbox_connect(user: User = Depends(get_current_user)):
    if not oauth_provider.available:
        raise HTTPException(status_code=404, detail="Google integration is not enabled")
    state = create_access_token(str(user.id), expires_minutes=10)
    return {"url": oauth_provider.mailbox_authorization_url(state)}


@router.get("/google/mailbox/callback")
def google_mailbox_callback(
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    base = f"{settings.frontend_url}/settings?mailbox="
    if not oauth_provider.available:
        raise HTTPException(status_code=404, detail="Google integration is not enabled")
    if error:
        return RedirectResponse(base + "denied", status_code=307)
    user_id = decode_access_token(state) if state else None
    if not user_id or not code:
        return RedirectResponse(base + "state", status_code=307)
    tokens = oauth_provider.exchange_code(
        code, redirect_uri=settings.google_mailbox_redirect_uri
    )
    refresh_token = (tokens or {}).get("refresh_token")
    if not refresh_token:
        return RedirectResponse(base + "exchange", status_code=307)
    user = db.get(User, int(user_id))
    if not user:
        return RedirectResponse(base + "state", status_code=307)
    user.gmail_read_token = refresh_token
    db.commit()
    add_log(db, user.id, "User", "Connected Gmail (read replies).")
    return RedirectResponse(base + "connected", status_code=307)


@router.post("/google/mailbox/disconnect", response_model=UserOut)
def google_mailbox_disconnect(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    user.gmail_read_token = None
    db.commit()
    db.refresh(user)
    add_log(db, user.id, "User", "Disconnected Gmail.")
    return user
