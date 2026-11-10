# Agentra

Agent-native browser middleware with real Chromium workers, semantic snapshots, reviewed actions and explicit recovery. The application is runnable and tested; see [REQUIREMENTS.md](REQUIREMENTS.md) for remaining production infrastructure requirements and unsupported browser surfaces.

## Run

Python 3.11+:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m playwright install chromium
$env:AGENTRA_TOKENS = '{"my-tenant":"YOUR_RANDOM_SECRET_AT_LEAST_32_CHARACTERS"}'
$env:AGENTRA_APPROVER_TOKEN = 'A_DIFFERENT_RANDOM_SECRET_AT_LEAST_32_CHARACTERS'
.venv\Scripts\python -m uvicorn agentra.server:app --host 127.0.0.1 --no-access-log
```

Generate secrets with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Keep the approver secret outside the agent's environment. OpenAPI documentation is at `/docs`. Run one worker: session ownership is in memory.

## Interaction sequence

### Watch the real browser

Before starting the service, set these PowerShell environment variables:

```powershell
$env:AGENTRA_HEADED = 'true'
$env:AGENTRA_SLOW_MO_MS = '300'
.venv\Scripts\python -m uvicorn agentra.server:app --host 127.0.0.1 --port 8000 --no-access-log
```

Keep your existing authentication variables configured. Stop and restart an already-running server to apply these settings, then create a new session. Each session opens an actual Chromium window on the **server's desktop**. Authorized actions run visibly in that window. Recovery uses the same display settings. Headless remains the default; `.env.example` is documentation, not automatically loaded. Slow motion is optional (0–2000 ms) and counts toward action deadlines.

For an immediate offline demonstration without restarting your server:

```powershell
.venv\Scripts\python -m scripts.live_demo
```

The demo opens a synthetic form, fills a message, clicks Save, checks the confirmation, and closes after 15 seconds. Only this fixed offline demo uses preapproved internal actions; the API's approval requirements are unchanged. No credentials or external websites are used. A desktop display is required; containers need separate display infrastructure. Manual interaction can invalidate snapshots, so request fresh state afterwards.

### API workflow

1. Authenticate with `Authorization: Bearer TOKEN`; POST `/sessions`.
2. GET `/sessions/{id}/state` for scoped references.
3. POST `/sessions/{id}/actions` with an `Idempotency-Key` and an Action JSON body.
4. Tenant ownership, schema, reference freshness and URL checks run under the session's FIFO asyncio lock.
5. Every mutation produces `AUTHORIZATION_REQUIRED`. A trusted approver reviews the exact action and sends its action ID plus the separate credential to `/sessions/{id}/authorize` within five minutes. Approval consumes that pending action once; stale checks run again.
6. Native Playwright locators perform actions. Explicit assertions verify effects; timeout receipts warn that an effect may already have happened.
7. A new monotonic snapshot invalidates earlier references. `/inspect` expands semantic subtrees; `/extract` streams accessibility text or a JSON envelope.

Example action: `{"kind":"NAVIGATE","url":"https://example.com"}`. Clicks require a postcondition, e.g. `{"kind":"CLICK","scoped_ref":"snap_2::tab_0::frame_0::@e0","postcondition":{"kind":"text","selector":"#receipt","value":"Saved"}}`.

## Boundaries and remaining production work

- CDP reads accessibility metadata only. Unique role/name locators address elements; ambiguous unnamed nodes are omitted. Open shadow DOM is supported by locators; closed shadow roots cannot be safely operated through this interface. Canvas/WebGL/image CAPTCHA requires an explicit human handoff, not automatic bypass.
- The 2,500-token ceiling covers serialized compact state using cl100k_base. Markdown extraction preserves ordinary headings, paragraphs, lists and tables and excludes form values. Extraction is capped at 20,000 nodes/2 million text characters; oversized documents fail explicitly and should be requested by smaller subtree. Document references allow whole-frame extraction. Merged table cells and code whitespace are not losslessly preserved.
- The authenticated local egress proxy resolves and validates all DNS answers, then connects to a numeric public IP. Chromium is configured to use it for HTTP(S), including loopback destinations; only ports 80 and 443 are allowed. TLS remains end-to-end. WebSockets/service workers are disabled. Independent OS network isolation is still needed to contain browser exploits or unsupported bypass transports. No arbitrary upload/download API is exposed.
- Each session owns a separate Chromium worker and context. A one-second RSS monitor closes workers exceeding `AGENTRA_SESSION_MEMORY_MB` (default 1024). This is a sampled threshold, not a kernel hard cap. Compose applies an aggregate memory/PID limit. Per-session cgroups/Job Objects and network namespaces remain deployment work. Recovery creates a blank worker without restoring credentials, URLs or actions.
- Mutation observers, form-value hashes and open-shadow hashes detect ordinary changes, but cannot guarantee freshness against hostile scripts or eliminate check-to-dispatch races. Snapshot READY describes capture stability; `/readiness` checks a specific target. Closed shadow roots cannot be reliably addressed. Canvas is explicitly flagged for human review.
- All mutations need approval because semantic risk inference cannot prove an action safe. An approved page may still execute arbitrary scripts/network side effects. Production needs scoped outbound effect enforcement and short-lived, action-bound approval identities. No secrets or typed text are deliberately logged; deploy with request-body logging disabled.
- Idle sessions expire after 15 minutes. Sessions, tabs, pending approvals, idempotency history, request bodies and action queues have bounds. Prometheus exposes sessions, action latency/outcomes, snapshot latency/tokens, recovery and resource stops. JSON audit events exclude page data, URLs, credentials and typed values. Validation errors omit submitted input.
- Container runs non-root with Chromium sandbox enabled. Supply a compatible host seccomp/user-namespace policy; never solve sandbox failures with `--no-sandbox`. Image build and deployment require separate verification.

## Verification

```powershell
python -m pytest -q
python -m mypy agentra
python -m scripts.benchmark
```

Tests use real Chromium plus controlled network fixtures for stale references, delayed hydration, frame topology, authorization, recovery, shadow DOM, extraction, egress and resource monitoring. `python -m scripts.network_smoke` separately tests public HTTPS navigation through the proxy. Benchmarks report empirical local measurements. Comprehensive adversarial browser/network testing and sustained resource stress testing remain release gates.

## Phase 2: worker lifecycle

- `GET /sessions/{sid}/status` reports ACTIVE, CRASHED or CLOSED lifecycle, worker generation, sanitized failure code and tab IDs. Deleted sessions return 404.
- `POST /sessions/{sid}/recover` recreates a crashed worker with one blank tab. Calling it on an active worker is a no-op. Only the owning tenant may recover; requests are serialized with other session operations.
- Browser disconnects and page crash events invalidate pending approvals and element references. Idempotency records remain: retrying an invalidated pending action returns FAILED, while completed receipts retain their historical result. No mutation is automatically retried.
- Queued operations check lifecycle after acquiring the session lock. Idle expiry rechecks activity under that lock; active operations refresh activity on completion. Worker resources are closed before temporary directories are removed.
- This phase tests real browser disconnection and recovery, cross-tenant denial, stale approvals, repeated recovery/deletion and idle cleanup. It does not yet test OS-level process kills, memory exhaustion, or recovery from loss of the shared Playwright driver. A browser worker is per session; the API/driver process is still shared.
- Existing benchmark results describe the phase-1 shared-browser architecture and must not be used to estimate this phase's memory overhead.

## Runtime controls and deployment

### Reading live, changing pages

Use `GET /sessions/{sid}/read?tab_id=tab_0` after navigation for fresh document content, title, URL, links and observation timestamp. Unlike action references, this read does not require the entire page to remain unchanged between requests. Navigation interruptions and empty documents are retried within a bounded deadline; clicks and typing retain strict stale-reference checks. `CONTENT_AVAILABLE` means content was read, not that a research question has been answered. Check source dates and facts before reporting task completion.

Known challenge pages return `HUMAN_REQUIRED` or `BLOCKED`; HTTP errors are not reported as verified navigation. Detection is heuristic, so callers must inspect returned content too. No CAPTCHA bypass, login bypass, or universal access guarantee is provided. Use a headed local session when manual interaction is needed; Docker headless sessions do not expose a human interaction window.

Run `.venv\Scripts\python scripts/search_task.py Hyderabad gold rate today` to search via Bing through the running API, or pass an HTTPS URL to read a source directly. This local test client reads the separate approval credential from `.env`; do not give that credential to an untrusted autonomous agent.

The Docker Compose project is named `mhp`, with service `agentra`. Run `python scripts/configure_local.py` once to generate ignored local credentials, then `docker compose up -d --build --wait`. Open http://127.0.0.1:8000/docs. `python scripts/api_smoke.py` verifies the live container and cleans up its test session. Credentials are in local `.env` and must not be committed. Stop the project with `docker compose down`.

The service uses `restart: unless-stopped`. Docker Desktop must be running; a stopped Docker engine makes the API unavailable. Container restarts lose in-memory sessions, so clients must create fresh sessions and must not replay uncertain actions.

`seccomp_profile.json` is the official Playwright v1.58.0 Docker profile, downloaded from https://github.com/microsoft/playwright/blob/v1.58.0/utils/docker/seccomp_profile.json. It permits Chromium user namespaces while keeping seccomp filtering. The tested configuration retains no-new-privileges and Docker's default capability set; dropping all capabilities prevented the browser from starting on this host.

`AGENTRA_MAX_SESSIONS` defaults to 8; `AGENTRA_MAX_TABS` defaults to 12. Configuration is server-controlled and validated at startup. `/health` supplies an unauthenticated availability check; `/metrics` requires a tenant token. Use one API worker because state is in memory.

`POST /sessions/{sid}/review` accepts the same action ID/approver credential body as authorize and returns the exact pending action and remaining validity. `/authorize` consumes it once. Clients must treat FAILED/TIMEOUT as potentially having effects. The approval key belongs to the trusted reviewer, never the autonomous agent. `POST /sessions/{sid}/readiness` accepts `scoped_ref` and `timeout_ms` and returns READY/PARTIAL/TIMEOUT for that target. These APIs are documented at `/docs` and `/openapi.json`.

For container deployment set the two secrets in your environment and use `docker compose up --build`. The Compose file binds localhost only, applies memory/PID constraints, uses a read-only root filesystem and temporary mounts, and preserves Chromium sandboxing. Host seccomp/user-namespace compatibility must be validated. External TLS, secret rotation, per-session kernel isolation and firewall enforcement are operator responsibilities. See [ARCHITECTURE.md](ARCHITECTURE.md) for sequence flow and trust boundaries, and [VALIDATION.md](VALIDATION.md) for actual test evidence.

Implementation references: [Playwright locators](https://playwright.dev/python/docs/locators), [network interception](https://playwright.dev/python/docs/network).

### Guest / judge observation room

Open http://127.0.0.1:8000/ and connect with a tenant API token, or run
`.venv\Scripts\python scripts/presentation.py` to open a connected presentation window
using the ignored local configuration without displaying its token.
Run your existing Agentra task in another terminal. The view shows that tenant's active
sessions, browser tabs, viewport images (roughly every second), and the latest 30 action
receipts per session. Full-screen and pause controls support presentations. No task is
simulated or started by the viewer. Short-lived sessions disappear when deleted.
The viewer is read-only; its credential remains in browser memory until disconnect/reload.
Present a dedicated demo session because screenshots can show personal page content.
This is a localhost presenter screen, not a public guest sharing service.
