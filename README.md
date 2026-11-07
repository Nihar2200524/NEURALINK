# Agentra

Executable first iteration of agent-native browser middleware. This is a development foundation, **not yet a hardened production release**.

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
- The token ceiling covers serialized compact state using cl100k_base. Accessibility-based extraction is not a full Markdown/table fidelity exporter. Large trees need further pagination and capture-cost controls.
- DNS validation rejects non-public addresses and checks intercepted requests, with service workers blocked. **It does not prevent DNS rebinding or fully mediate redirect-chain/browser traffic. Deploy only behind an independently enforced egress proxy/firewall before untrusted browsing.** WebSockets are currently disabled. No arbitrary upload/download API is exposed.
- Contexts isolate cookies; they are not OS sandboxes. A temporary directory is reserved per session, but Chromium is shared. Per-session processes/cgroups, memory caps, network namespaces and automatic worker reconstruction remain required. Browser failure fails closed; restarting loses ephemeral sessions. Do not replay uncertain mutations.
- Mutation observers catch ordinary DOM changes, not hostile JavaScript tampering, all shadow-root changes, or the race between checking and dispatching. This is not a deterministic security guarantee. Snapshot READY means stable capture, not universal hydration; actionability is enforced on the target during execution.
- All mutations need approval because semantic risk inference cannot prove an action safe. An approved page may still execute arbitrary scripts/network side effects. Production needs scoped outbound effect enforcement and short-lived, action-bound approval identities. No secrets or typed text are deliberately logged; deploy with request-body logging disabled.
- Idle sessions expire after 15 minutes. Sessions, pending approvals and idempotency history have bounds. Prometheus exposes snapshot durations and token sizes; tenant-level telemetry and structured audit receipts need expansion.
- Container runs non-root with Chromium sandbox enabled. Supply a compatible host seccomp/user-namespace policy; never solve sandbox failures with `--no-sandbox`. Image build and deployment require separate verification.

## Verification

```powershell
python -m pytest -q
python -m mypy agentra
python -m scripts.benchmark
```

Tests use real Chromium and synthetic HTML for stale references, delayed hydration, multi-tab/frame topology and approval gates. Benchmarks report actual local measurements; no performance claims are assumed. Full multi-origin, crash-recovery, adversarial egress and resource stress coverage remains to be added.

Implementation references: [Playwright locators](https://playwright.dev/python/docs/locators), [network interception](https://playwright.dev/python/docs/network).
