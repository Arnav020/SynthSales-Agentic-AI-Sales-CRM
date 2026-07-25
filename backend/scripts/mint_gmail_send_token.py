"""Mint the GMAIL_SEND_REFRESH_TOKEN for the Gmail API sender (providers/email.py).

One-time, run locally on the dev machine (NOT on a server):

    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\mint_gmail_send_token.py [--send-test you@example.com]

It reuses the app's Google OAuth client (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET from
backend/.env) and the already-registered dev redirect URI
(http://127.0.0.1:8000/api/auth/google/callback), so no Google Cloud console changes
are needed. Stop uvicorn first — the script itself listens on that port to catch the
OAuth callback.

Flow: opens the Google consent screen in your browser (sign in with the Gmail account
the app should SEND FROM), captures the authorization code on the local callback,
exchanges it for a refresh token (scope: gmail.send only), and prints the env lines to
paste into the deploy host (e.g. the Render service's Environment tab). With
--send-test it also proves the grant works by sending a real email through the Gmail
API using the fresh access token.

Caveat: if the OAuth consent screen is in "Testing" publish status, Google (a) refuses
consent with `access_denied` for any account not listed under OAuth consent screen →
Test users, and (b) expires refresh tokens after 7 days. Setting the publish status to
"In production" (Google Cloud console → APIs & Services → OAuth consent screen) fixes
both — do that before minting the token you'll deploy.
"""
from __future__ import annotations

import argparse
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPE = "https://www.googleapis.com/auth/gmail.send"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8000/api/auth/google/callback"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def read_env(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE .env parser (enough for this script; no interpolation)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    # utf-8-sig strips the BOM PowerShell-written .env files start with.
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        value = raw.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


class _Server(HTTPServer):
    # The stdlib default (allow_reuse_address=True → SO_REUSEADDR) lets the bind
    # SUCCEED on Windows even while uvicorn is still listening on the port, and
    # the OAuth redirect then lands on uvicorn instead of us. False restores a
    # loud WSAEADDRINUSE so "stop uvicorn first" actually gets diagnosed.
    allow_reuse_address = False


class _Callback(BaseHTTPRequestHandler):
    """Catches the single OAuth redirect; stores code/error on the server object."""

    # Without a timeout, one silent connection (browser preconnect, AV scanner)
    # blocks the single-threaded server forever and shutdown() never returns.
    timeout = 15

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        query = parse_qs(urlparse(self.path).query)
        state = query.get("state", [""])[0]
        error = query.get("error", [""])[0]
        code = query.get("code", [""])[0]
        if state != self.server.expected_state:  # type: ignore[attr-defined]
            self._page(400, "State mismatch — close this tab and re-run the script.")
            return
        try:
            if error or not code:
                self.server.oauth_error = error or "no code returned"  # type: ignore[attr-defined]
                self._page(400, f"Consent failed: {error or 'no code returned'}. You can close this tab.")
            else:
                self.server.oauth_code = code  # type: ignore[attr-defined]
                self._page(200, "Consent captured — return to the terminal. You can close this tab.")
        finally:
            # Signal even if writing the response page fails (tab closed mid-write):
            # the code/error is already stored and must not be lost to a socket error.
            self.server.done.set()  # type: ignore[attr-defined]

    def _page(self, status: int, message: str) -> None:
        body = f"<html><body style='font-family:sans-serif'><h2>SynthSales token mint</h2><p>{message}</p></body></html>"
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:  # silence per-request stderr noise
        pass


def start_server(redirect_uri: str, state: str) -> _Server:
    """Bind the callback listener (before any browser tab opens)."""
    parsed = urlparse(redirect_uri)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or (443 if parsed.scheme == "https" else 80)
    if host not in ("127.0.0.1", "localhost"):
        sys.exit(
            f"GOOGLE_REDIRECT_URI is {redirect_uri} — minting locally needs the "
            "registered loopback URI (http://127.0.0.1:8000/api/auth/google/callback). "
            "Remove/adjust GOOGLE_REDIRECT_URI in backend/.env and re-run."
        )
    try:
        server = _Server((host, port), _Callback)
    except OSError as exc:
        sys.exit(
            f"Cannot listen on {host}:{port} ({exc}).\n"
            "Stop uvicorn (or whatever holds the port) and re-run — the script needs "
            "the port to catch Google's redirect."
        )
    server.expected_state = state  # type: ignore[attr-defined]
    server.oauth_code = ""  # type: ignore[attr-defined]
    server.oauth_error = ""  # type: ignore[attr-defined]
    server.done = threading.Event()  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def wait_for_code(server: _Server) -> str:
    try:
        # Wait until the browser round-trip lands (no timeout: consent can take a while).
        while not server.done.wait(timeout=1.0):  # type: ignore[attr-defined]
            pass
    except KeyboardInterrupt:
        sys.exit("\nAborted.")
    finally:
        server.shutdown()
        server.server_close()
    if server.oauth_error:  # type: ignore[attr-defined]
        hint = ""
        if "access_denied" in server.oauth_error:  # type: ignore[attr-defined]
            hint = (
                "\nIf the consent screen is in 'Testing' publish status, the account "
                "must be listed under OAuth consent screen -> Test users (or set the "
                "publish status to 'In production')."
            )
        sys.exit(f"Google returned an error: {server.oauth_error}{hint}")  # type: ignore[attr-defined]
    return server.oauth_code  # type: ignore[attr-defined]


def send_test_email(access_token: str, sender: str, recipient: str) -> bool:
    from email.mime.text import MIMEText
    import base64

    msg = MIMEText("Gmail API sender is working — sent by mint_gmail_send_token.py.")
    msg["To"] = recipient
    msg["From"] = sender or recipient
    msg["Subject"] = "SynthSales Gmail sender test"
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        resp = httpx.post(
            GMAIL_SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        print(f"Test send FAILED (network): {exc}")
        return False
    if resp.status_code == 200:
        print(f"Test email sent to {recipient} — check the inbox.")
        return True
    print(f"Test send FAILED: HTTP {resp.status_code} {resp.text[:300]}")
    if resp.status_code == 403 and "accessNotConfigured" in resp.text:
        print(
            "The Gmail API is not enabled on this Google Cloud project - enable it at "
            "APIs & Services -> Library -> Gmail API. The refresh token above is still valid."
        )
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--send-test",
        metavar="EMAIL",
        help="after minting, send a real test email to this address via the Gmail API",
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="print the consent URL and exit (no listener, no browser) — for debugging",
    )
    args = parser.parse_args()

    env = read_env(ENV_PATH)
    client_id = env.get("GOOGLE_CLIENT_ID", "")
    client_secret = env.get("GOOGLE_CLIENT_SECRET", "")
    redirect_uri = env.get("GOOGLE_REDIRECT_URI") or DEFAULT_REDIRECT_URI
    if not client_id or not client_secret:
        sys.exit(f"GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not found in {ENV_PATH}.")

    state = secrets.token_urlsafe(24)
    consent_url = GOOGLE_AUTH_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            # offline + consent forces Google to return a refresh token even if
            # this account granted the scope before (mirrors providers/oauth.py).
            "access_type": "offline",
            "prompt": "select_account consent",
        }
    )
    if args.print_url:
        print(consent_url)
        return

    # Bind BEFORE opening the browser so a held port aborts while no consent tab
    # is in flight (a code delivered to the wrong listener is unrecoverable).
    server = start_server(redirect_uri, state)
    print("Listening for the OAuth callback...")
    print("Opening the Google consent screen — sign in with the Gmail account the app")
    print("should SEND FROM. If no browser opens, paste this URL yourself:\n")
    print(consent_url + "\n")
    webbrowser.open(consent_url)

    code = wait_for_code(server)
    print("Code received — exchanging for tokens...")
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30.0,
    )
    if resp.status_code != 200:
        sys.exit(f"Token exchange failed: HTTP {resp.status_code} {resp.text[:300]}")
    tokens = resp.json()
    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        sys.exit(
            "Google returned no refresh_token (response had: "
            f"{', '.join(sorted(tokens))}). Re-run and make sure you complete the "
            "consent screen — 'prompt=consent' should force one."
        )

    # Print the token BEFORE the optional test send: a failed test must never
    # discard a successfully minted token.
    print("\nSuccess. Set these on the deploy host (Render -> synthsales-api -> Environment):\n")
    print(f"GMAIL_SEND_REFRESH_TOKEN={refresh_token}")
    print("# GMAIL_SEND_CLIENT_ID / GMAIL_SEND_CLIENT_SECRET are only needed if the")
    print("# host's GOOGLE_CLIENT_ID/SECRET differ from the client used just now.")
    print("\nAlso set SMTP_FROM to the SAME Gmail account you just authorized, e.g.")
    print("SMTP_FROM=SynthSales <your-account@gmail.com>")
    print('\nThen verify: GET /health should report "email_mode": "gmail".')

    if args.send_test:
        ok = send_test_email(tokens.get("access_token", ""), env.get("SMTP_FROM", ""), args.send_test)
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
