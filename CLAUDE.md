# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

"Agentic CRM" (product name **SynthSales**, formerly Reachly) is an AI-powered B2B outreach platform: User(Company's representative) upload a CSV of potential customer's companies,and details of their product and customer requirements then an 8-agent pipeline will researches → scores → finds contacts → guesses & verifies emails of Sales decision makers →
drafts personalized outreach → tracks replies till they are ready for a meetings or reject the deal -> Fix meeting if they are ready -> Send a Google Meet link -> reads inbound replies & classifies intent. 
Two independent apps in one repo:

- `backend/` — FastAPI + PostgreSQL (SQLAlchemy 2.0). Branding is now **SynthSales** throughout (the
  old "Reachly" name was fully retired in the 2026-06-19 deploy pass — container `synthsales_postgres`,
  db/user `synthsales`, `APP_NAME="SynthSales API"`).
- `web/` — Next.js 16 + React 19 + Tailwind v4 (App Router). All user-facing branding is **SynthSales**;
  no "reachly" string may appear in `web/src`. Talks to the backend over REST (polling for live data).

**`CHANGELOG.md` is a running context log** (renamed from `README.md` — that file is now the public-facing project
README) — it is updated after each substantial task with what changed and why; keep that convention when you finish
meaningful work.

## Running the stack

Two terminals. **Postgres runs on host port 5433** (not 5432 — a local Postgres already owns 5432).

```powershell
# Backend (terminal 1)
cd "C:\My Work\Agentic CRM\backend"
docker compose up -d                                          # Postgres 16, container "synthsales_postgres"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
#   API http://127.0.0.1:8000 · Swagger /docs · /health shows which integrations are live

# Frontend (terminal 2)
cd "C:\My Work\Agentic CRM\web"
npm run dev        # http://localhost:3000
npm run build      # production build — this is also the typecheck gate
npm run lint       # eslint (flat config)
```

Demo login (seeded automatically in **development**, idempotent): **jordan@apexcloud.com / password123**.
The demo seed is gated to dev (or an explicit `SEED_DEMO_DATA=true`), so production boots clean.

The backend **boots with zero credentials** in development — every external integration degrades
gracefully (see Providers below). `web/.env.local` sets `NEXT_PUBLIC_API_URL` (defaults to
`http://127.0.0.1:8000`). To enable real integrations, copy `backend/.env.example` → `backend/.env` and
fill keys. **For a non-development deploy:** set `ENVIRONMENT` to a non-`development` value, a strong
`SECRET_KEY` (≥32 chars — `lifespan` refuses to boot otherwise), your prod `CORS_ORIGINS` and
`DATABASE_URL`, and **`SERPER_API_KEYS`** — web search (`ddgs`) is rate-limited from datacenter IPs and
fails on a deploy, so without a Serper key the pipeline runs blind (no research, no contacts). Outside
development, interactive `/docs` is disabled and the demo user is not seeded.

### Verification / testing

There is **no automated test suite** (no pytest, no jest). The de-facto verification loop is:
- Frontend: `npm run build` must pass (it typechecks every route).
- Backend: hit `GET /health` to confirm integration wiring, then smoke-test live endpoints via `/docs`.
- DB inspection: **`.\db.ps1`** (repo root) is a read-only Postgres browser — `.\db.ps1` for the menu,
  `.\db.ps1 user <id|email>` for a per-user tree, `.\db.ps1 health` for row counts, `.\db.ps1 sql "<SELECT>"`
  for ad-hoc queries. Use it to confirm what the pipeline actually wrote.
- CSV upload: **`sample-companies.csv`** (`extra/`, gitignored/local-only) — 15 real B2B companies for
  exercising the upload → pipeline flow (and the non-approved 2-company preview cap).

## Architecture

### The agent pipeline (the heart of the system)

`backend/app/agents/` holds 8 agents registered in `base.py::AGENT_REGISTRY` (order matters):
**enrichment → scoring → employee_finder → email_guess_verification → outreach → tracking → meeting → reply_classifier**.

`agents/orchestrator.py` is the only place that sequences them. Two entry points:
- `run_campaign_pipeline()` — the full Phase 1–6 run a "Run all agents" click triggers. Before mutating anything it snapshots the campaign's pipeline output (company agent-fields + contacts + drafts) for a **one-level 24h undo** (`services/snapshots.py`); `POST /api/campaigns/{id}/restore` rolls it back and consumes it, `GET …/snapshot` reports availability. The UI shows a confirmation warning before running.
- `run_agent_for_campaign(..., key, force)` — runs one stage on demand (the per-agent Re-run buttons). A forced re-run (`force=True`) first snapshots for undo, then `clear_successors` clears that agent's downstream outputs — **except** locked contacts (any contact with a sent `Thread` → a live conversation) and meetings, which no clear path ever deletes (`services/pipeline_locks.py`). Undo is blocked once the campaign has any live conversation. A non-forced run is additive (no snapshot, no cascade).
  `RUNNABLE_KEYS` excludes `meeting` (it only fires when a user books a meeting in Conversations).

Non-obvious orchestration rules you must respect when editing agents:
- **`email_guess_verification` is one merged agent** — it guesses likely addresses then verifies them
  in a single pass (`guess_emails()` runs inside `verification_agent.run()`). It stores a confirmed
  `Verified` address, or — on a **catch-all** server that can't confirm a specific mailbox — the top
  guess marked `Risky` (one credit per catch-all domain, not one per pattern, via `verifier.classify`
  + a per-domain short-circuit). When `HUNTER_API_KEY` is set it first does ONE Hunter.io lookup per
  company (the top contact's real email + the company's actual mail domain), then resolves the rest
  via guess+verify; `email_guess`/`verification` are no longer separate keys.
- **`_walk_for_contactable()`** is the contact-finding fallback the user explicitly asked for: walk
  ranked companies, run the employee finder, and if a Qualified company yields *no real LinkedIn
  contacts*, demote it `Qualified → Reviewed` and promote the next-best company into the top-N slot.
  Quota = `campaign.top_n`.
- **`force=True`** means "discard prior output and redo": it wipes stale contacts/drafts/verdicts so a
  re-run produces a clean picture instead of a stale+new mix. The full pipeline passes `force=True` to
  the finder/guess-verify/outreach phases; bulk incremental runs default to `False`. **Exception:** the
  guess-verify agent **preserves already-`Verified` addresses** even on `force` (`_confirmed()`) —
  they're confirmed and paid-for, so it never re-verifies them (no wasted credit, no blanking when the
  verifier is out of credit) and reuses their mail domain for the company's other contacts.
- Agents never fabricate. The employee finder returns **real** `site:linkedin.com/in/` profiles or
  **zero contacts** — do not reintroduce hardcoded name lists. Enrichment detects parked/dead domains
  and writes honest low-confidence summaries rather than hallucinating a profile.
- **Finder search is escalating + role-gated** — `find_linkedin_profiles` runs precise
  `site:linkedin.com/in/` queries, then simpler high-recall queries (`<brand> head of sales`), then a
  founder/CEO fallback across all aliases, reading SERP titles only (never opening LinkedIn), and keeps
  only roles passing a deterministic commercial-role gate (`_is_commercial_role`). Users can also add
  contacts manually via `POST /api/companies/{id}/contacts`.
- **`reply_classifier` is the inbound half of engagement** — it is NOT part of
  `run_campaign_pipeline` and is excluded from `RUNNABLE_KEYS` (like `meeting`). It runs via
  `POST /api/conversations/sync` (on demand) and a second scheduler job (`INBOUND_POLL_MINUTES`,
  default 5). It reads replies through `providers/inbound.py` (per-user Gmail read + IMAP
  fallback), de-dupes by `Message.external_id`, classifies via `ai.complete_json`, and acts: a
  high-confidence *not-interested* sets `Contact.do_not_contact=True` + `Thread.stage="Closed"`
  (reusing the Step 04 suppression); interested/meeting-ready advance to `Negotiating` + surface;
  everything else only surfaces. It never opts a contact out without AI. **In the pipeline rail
  (`web/.../PipelineTimeline.tsx`) the reply reader is the only inbound stage shown — the follow-up
  tracker is hidden (it fires on the scheduler, not a user click) and the reply reader is sorted just
  above the meeting scheduler (a display-only override of `meeting.order`; the backend still orders
  `reply_classifier` last). Both rows deep-link to Conversations.**
- **Autonomous replies (off by default)** — by default `reply_classifier` only surfaces/advances/
  closes; it does **not** send. When the user turns on `User.autonomous_replies` (Settings; also
  requires `outbound_enabled`), the classifier routes high-confidence, actionable replies through
  `services/auto_reply.py`, which composes and **sends a real email** and updates state:
  *not-interested* → a warm closing note + `do_not_contact` + `Closed`; *interested/meeting-ready*
  → auto-books a meeting (real Google Meet link) and sends it; *question* → answers from the
  campaign's product info only (else proposes a call). `gates_pass()` enforces every gate
  (`outbound_enabled` + `autonomous_replies` + a contactable, non-suppressed contact + an actionable
  intent + confidence ≥ `REPLY_OPTOUT_MIN_CONFIDENCE`); any handler error falls back to surfacing.

Each agent extends `agents/base.py::Agent` and calls `self.mark(db, owner_id, "Running"|"Idle"|"Error")`
to drive the per-user `agent_configs` status the UI reads.

### Providers — everything degrades gracefully

`backend/app/providers/` wraps all external I/O behind interfaces that work with no keys:
- **`ai.py`** — ordered backend chain (Gemini → Groq → OpenRouter) called via OpenAI-style REST with
  `httpx` (no SDKs). On HTTP 429 the backend is cooled down 60s and the call fails over to the next.
  Configure with `AI_PROVIDERS=gemini,groq,openrouter`. With no key, `complete()` returns `""` and
  callers fall back to deterministic heuristics.
- **`verification.py`** — 2 layers. Free layer (always on): syntax → role-account → disposable
  blocklist → **MX DNS lookup**. Paid layer (survivors only): **Verifalia** (preferred when
  configured — more credits) or **ZeroBounce**. No SMTP probing (reputation-safe). Verdicts rank
  Verified > Risky > Unknown > Invalid. **The merged guess-verify agent stores an address on a
  paid-provider `Verified` (confirmed mailbox) or, on a catch-all server, the best guess as `Risky`;
  it stops probing at the first hit and flags a domain catch-all once, so a paid key produces
  contactable emails without burning a credit per pattern. With no paid key, contacts stay
  `Unknown`/blank and outreach drafts nothing.**
- **`hunter.py`** — optional Hunter.io email finder (`HUNTER_API_KEY`). The guess-verify agent calls it
  **once per company** to resolve the top contact's real email + the company's actual mail domain
  (authoritative, unlike the DuckDuckGo `find_email_domain` fallback); the other contacts reuse that
  domain via the paid verify path. Used sparingly (Hunter's free tier is small); absent → the agent
  falls back to web domain-discovery + guessing. `/health` reports `email_finder: hunter|off`.
- **`email.py`** — Gmail API / SMTP / **console** fallback. In console mode (default) emails are logged,
  and the signup OTP is also returned to the UI as `dev_otp` so you can verify without email setup.
- **`calendar.py`** — per-user Google Calendar. When a user connects their calendar (Settings →
  Connect Google Calendar; offline consent for `calendar.events`, refresh token stored on
  `User.google_calendar_token`), booking a meeting creates a real Calendar event with a Google Meet
  link on **their** calendar. No connection → falls back to a user-supplied link (else the booking
  route returns 422). Never fabricates a link.
- **`inbound.py`** — per-user inbound reader. Gmail API read (reconstructed from
  `User.gmail_read_token`, `gmail.readonly`) with a stdlib `imaplib` global fallback. Returns
  normalized `InboundMessage`s; returns `[]` and never raises on any error. No mailbox connected
  → no ingestion.
- **`search.py`** — web search behind one `search()` chokepoint, routed through a configurable backend
  chain (`SEARCH_ORDER`, default `ddgs,serper`). **DuckDuckGo** (`ddgs`, no key) is free but gets
  rate-limited from datacenter IPs, so it fails on a deploy; **Serper.io** (`SERPER_API_KEYS`, real Google
  results) is the deploy backend — its `organic[]` results are mapped to the same `{title,href,body}` shape
  so callers stay backend-agnostic. The key pool is **drained one key at a time** (a key is used until it
  403s "out of credits", then the next — sequential, not round-robin; a 429 cools that key 60s). A **ddgs
  circuit breaker** trips after 3 consecutive empty/failed ddgs calls and skips ddgs for 10 min (straight to
  Serper) so a blocked scraper can't add a failed round-trip before every search; one success resets it.
  With no Serper key + ddgs blocked, search degrades to `[]` (callers fall back). Exposes
  `domain_status() → live|parked|dead`, `find_linkedin_profiles()`, and `find_email_domain()` (the
  company's real mail domain — scrapes the company's own site for a published info@/sales@ first, then an
  email-format search; rejects free webmail, aggregators, and asset filenames like `logo@2x.png`).
  `/health` reports `search: "ddgs → serper(N keys)"|"none"`.

### Outbound email kill-switch (safety — do not bypass)

`User.outbound_enabled` **defaults `False`**. No real email reaches a prospect until the user turns
sending on in Settings → Email. Gated paths return 403 / skip while paused: conversation send and manual replies, the
tracking agent's auto follow-ups, the meeting agent's contact email, and the autonomous reply
handlers (`services/auto_reply.py`, additionally gated by `User.autonomous_replies`). **Exempt:** signup OTP and
"send test" (to self) always work.

### Access gating (anti-abuse — do not bypass)

New accounts can *preview* the product but can't run it at scale until an admin approves them.
`User.access_status` (`none|pending|approved|rejected`) + `User.has_access` (admin **or** approved) drive
two layers; `services/access.py` holds the agent-key partition + the `require_access()` 403 guard.
- **Approved-only:** the **outreach / tracking / meeting / reply_classifier** agents and **outbound
  sending**. The outbound setter (`PATCH /api/auth/me outbound_enabled=true`), `POST /api/conversations/sync`,
  and book-meeting all `require_access`; the scheduler skips non-approved users; outbound stays the user's
  own kill-switch once approved.
- **Credit-capped (non-approved):** the **free** agents stay runnable but capped — both "Run all"
  (`orchestrator._run_preview_pipeline`) and per-agent runs (`_run_agent_capped`) enrich + score only the
  first `PREVIEW_COMPANIES` (2) companies and resolve ONE contact + email for the top one;
  `companies/{id}/find-contacts` is capped to one contact. Runs are repeatable (capped = cheap). Only the
  **gated** agents 403 (`run-agent` on a gated key → the access modal). The web **research + contacts**
  pages show the 2 / 1 preview rows clear and a blurred `<LockedPreview>` panel (with a Request-access
  button) for the rest; in the pipeline rail only the gated agents show "Requires access".

A user requests access via `POST /api/access/request` (→ pending); an admin approves/rejects from the
control room (`GET /api/admin/access-requests`, `POST /api/admin/users/{id}/access`). Existing users were
grandfathered to `approved`; admins are always approved.

### Data model & status lifecycles

`backend/app/models.py` — Users, Campaigns, Companies, Contacts, EmailDrafts, Threads+Messages,
Meetings, Notifications, Logs, AgentConfigs, plus VerifiedContact (the global cross-tenant verified-contact
directory, keyed by company domain/name — finder + guess-verify reuse it to skip re-finding and paid
verification), PipelineSnapshot (the per-campaign one-level 24h undo buffer), and RevokedToken (the JWT
logout/revocation blocklist, keyed by token `jti`; expired rows purged hourly by the scheduler). All child
rows cascade-delete from their owner. Key status fields the UI depends on:
- `Company.status`: `Researching` (not yet processed) → `Qualified` (top-N) | `Reviewed` (scored but
  not selected) | `Excluded`/`Approved`/`Contacted` (user-set, preserved across re-runs).
- `Company.domain_status`: `live|parked|dead|unknown`; `enrichment_confidence` (0–100) caps scoring so
  a parked/dead-domain company can't display as "Strong".
- `Contact.verification`: `Verified|Risky|Unknown|Invalid` (the merged guess-verify agent persists
  `Verified` (confirmed) or `Risky` (best-guess on a catch-all server) with an address, else `Unknown`
  with no address). `EmailDraft.state`, `Thread.stage`.
  `Contact.do_not_contact` is set by `reply_classifier` on a high-confidence not-interested reply (and
  cleared by the human reopen control); `Message.intent` holds the classified reply intent.
- `User.access_status`: `none|pending|approved|rejected` — the anti-abuse gate (see Access gating above);
  `User.has_access` is `is_admin or approved`.

### Schema migrations

**Alembic** owns the schema (adopted 2026-06-19). `main.py::lifespan` runs `alembic upgrade head` on boot
(`_run_migrations()`), so a fresh DB is built from the migrations and an existing one is brought current —
the old `create_all` + idempotent `ALTER TABLE` block is gone. Running migrations on boot is safe because
the deploy is single-worker.

- Migration scripts live in `backend/alembic/versions/`; `backend/alembic/env.py` pulls the DB URL +
  target metadata from `app.core.config.settings` + `app.models`, so autogenerate diffs against the live
  models and migrations always hit the same DB the app uses.
- **When you change a model** (add/alter a column, table, or index), author a migration:
  `cd backend; .\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "<what changed>"`, review
  the generated file in `alembic/versions/`, then apply it with `... -m alembic upgrade head` (or just
  restart the app — it upgrades on boot). Confirm there's no drift with `... -m alembic check`
  ("No new upgrade operations detected").
- The baseline revision (`ab18fda68ae2`) captures the pre-Alembic schema; existing dev/prod DBs were
  `alembic stamp`-ed to it. The runtime admin auto-grant (`ADMIN_EMAILS`) stays in `lifespan` — it's
  config-driven, not schema.

### Cross-cutting services

- `services/events.py` — `add_log()` / `add_notification()` are the single way to record audit logs and
  notifications. Use these, don't write `Log`/`Notification` rows directly. The web app surfaces both by
  **polling** REST (`GET /api/logs`, `GET /api/notifications`) — there is no WebSocket/push layer (removed
  2026-06-19; notifications poll every 30s, activity/live-log every 5s, the pipeline view every 3s).
- `workers/scheduler.py` — APScheduler polls the tracking agent every `FOLLOWUP_INTERVAL_MINUTES`
  (default 15, the **poll cadence**) for all users. Disable with `ENABLE_SCHEDULER=false`. A thread
  gets an automatic follow-up only after our last message goes unanswered for `FOLLOWUP_DELAY_DAYS`
  (default 7 — decoupled from the poll cadence); after `MAX_FOLLOW_UPS` (default 3) unanswered nudges
  it auto-advances to the terminal `Stalled` stage. `Contact.do_not_contact` suppresses every send
  path (outreach draft, send, auto follow-up, meeting invite). A second job polls the inbound reply
  reader (the `reply_classifier` agent) every `INBOUND_POLL_MINUTES` (default 5) for every user with
  a connected mailbox. Both action jobs take a Postgres advisory lock per tick (`_job_lock` →
  `pg_try_advisory_xact_lock`), so running the scheduler under multiple workers can't double-fire them —
  only one process executes each tick (the idempotent purge jobs are unguarded).

### API surface & auth

Routers in `backend/app/api/routers/`, all prefixed `/api/<name>`. Auth is JWT (`api/deps.py::
get_current_user`); cross-tenant `/api/admin/*` routes require `require_admin` (a user is admin if
`is_admin` is set, auto-granted at startup/verification for emails in `ADMIN_EMAILS`).

Auth additions (2026-06-11): `POST /api/auth/forgot-password` (throttled, anti-enumeration generic
response) and `POST /api/auth/reset-password` (OTP ladder mirroring verify-otp) power the real
password-reset flow; `GET /api/notifications` takes `limit` (default 50, max 500).

Auth/API additions (2026-06-19): `POST /api/auth/logout` revokes the caller's token — tokens carry a
`jti`, logout records it in the `revoked_tokens` blocklist, and `get_current_user` rejects revoked tokens
(no refresh tokens — the 7-day token + revocation suffices). The four list endpoints (companies via
`/api/campaigns/{id}/companies`, contacts, emails, conversations) accept optional `limit`/`offset` via the
shared `api/pagination.py::Page` dependency (responses stay plain arrays; an omitted `limit` ⇒ a 500-row
ceiling). User-level delete exists for companies (`DELETE /api/companies/{id}`) and contacts
(`DELETE /api/contacts/{id}`) — owner-scoped, children cascade, blocked `409` if a live conversation exists
unless `?force=true`.

Access gating endpoints (2026-06-19): `POST /api/access/request` (user → pending); admin control room
`GET /api/admin/access-requests` + `POST /api/admin/users/{id}/access` (`{decision: approve|reject, note?}`).
See "Access gating" above.

Frontend wiring (`web/src/lib/`): `api.ts` is the typed client (token in `localStorage["synthsales_token"]`,
authenticated 401s auto-redirect to `/login`), `api-types.ts` mirrors backend schemas, `hooks.ts` has
`useApi` (fetch) + `useAction` (keyed mutations with toasts). `components/AuthProvider.tsx` wraps the
`(app)` route group and guards routes (`useAuth() → {me, refresh, signOut}`). App pages run on live API
data; canonical status→tone maps + `AGENT_LABELS` live in `lib/constants.ts` (exhaustive via `satisfies`).
Route groups: `(marketing)` (landing/about/contact/changelog/docs/privacy/terms), `(auth)` (login/signup/forgot-password/
oauth-callback), `(app)` (dashboard, campaigns [+new, +/[id] pipeline page], research [+/[id]],
contacts, outreach, conversations, meetings, agents, integrations, notifications, activity, settings,
admin). Billing was dropped in the 2026-06 rebuild; Integrations/Activity/Admin are new.

### Read-only demo account (frontend-only, no backend)

A **"View live demo"** button on the **signup** page (`enterDemo()` in `api.ts`) drops a visitor into a
**static, read-only demo** showing the full product with dummy data for every agent — **nothing works**.
It is purely frontend: a `localStorage["synthsales_demo"]` flag + a sentinel token (`"demo"`) make the
existing auth guards pass, and `api.ts::request()` intercepts **authenticated** traffic — GETs resolve
from `lib/demo-fixtures.ts`, every mutation throws `DemoError` (which `useAction` turns into a friendly
"create an account" toast). **No network call leaves the browser in demo mode.** Public auth endpoints
(`auth:false`: login/register/etc.) bypass the demo so a real login always works; `setToken()` (a real
login) clears the demo flag, and `signOut`/the modal's "Create account" call `exitDemo()`.
- `lib/demo-fixtures.ts` — the dataset (mirrors `services/seed.py` shapes) + `resolveDemo(path)` which
  regex-routes a GET path to its fixture (unknown paths → empty default, never crash). Demo campaigns are
  deliberately **stopped at different pipeline agents** (per-campaign `CAMPAIGN_PIPELINE`) and meeting dates
  are **relative to now** (`offsetISO`) so "upcoming" stays upcoming. Edit data here.
- `lib/demo.ts` — `useDemo()` (a `useSyncExternalStore` hook, hydration-safe) + the per-session
  `synthsales_demo_welcomed` flag helpers.
- `components/DemoWelcomeModal.tsx` — centered once-per-session warning (OK / Create account), mounted in
  `AuthProvider`. A "Demo · read-only" Topbar badge + greyed-out primary buttons (Run all agents, New/Create
  campaign, Send, Book meeting, all gated on `useDemo()`) reinforce that it's inert.
- All localStorage keys are now `synthsales_*` — `synthsales_token` (JWT), `synthsales_theme` (dark-mode),
  and the demo flags (`synthsales_demo`, `synthsales_demo_welcomed`); the legacy `sellari_*` keys were
  retired in the 2026-06-19 deploy pass. The Integrations page reads `/health` (a public `auth:false` GET)
  so it shows real backend status even in demo — harmless.

## Frontend gotcha — Next.js 16 is not the Next.js you know

Per `web/AGENTS.md`: this is Next.js 16, which has breaking changes vs. older versions in your training
data (APIs, conventions, file structure). **Read the relevant guide under `web/node_modules/next/dist/docs/`
before writing frontend code**, and heed deprecation notices. Routes use the App Router with
`(marketing)`, `(auth)` and `(app)` route groups. The design system lives in Tailwind v4 `@theme`
tokens in `src/app/globals.css`, styled after the `UI.webp` reference (`extra/`, local-only): warm cream
editorial minimalism — cream/paper surfaces, ink text, hairline `line` borders, terracotta accent,
dark `band` sections, `moss/amber(+amber-deep)/rust` status colors, Schibsted Grotesk + Instrument
Serif italic display pairing (`.display` + `.display em`), numbered eyebrows. `ink-faint` is for
decorative labels only (meaning-bearing small text uses `ink-soft`); the Tailwind `amber-*` ramp is
retired (bare `amber` + `amber-deep` only).

## Environment notes

- Platform is **Windows + PowerShell**; the backend Python lives in `backend\.venv` (invoke as
  `.\.venv\Scripts\python.exe`). Node may not be on a fresh shell's PATH (`C:\Program Files\nodejs`).
- `docker compose` must be running for the backend to reach Postgres on `localhost:5433`.
- **`uvicorn --reload` is unreliable here** — watchfiles can silently miss edits on Windows after rapid
  changes, leaving the worker on stale code. After changing backend code, **restart uvicorn** rather than
  trusting auto-reload (or you'll test stale behavior). Next.js/Turbopack hot-reload on the frontend is fine.
