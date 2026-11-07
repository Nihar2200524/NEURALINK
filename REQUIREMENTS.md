# Specification coverage and release gates

This is a concrete status record, not a claim of enterprise certification.

| Area | Implemented and locally exercised | Remaining / deliberate limits |
| --- | --- | --- |
| Authentication | High-entropy bearer mapping, ownership checks, separate approver credential | External identity provider, key rotation and remote TLS are deployment concerns |
| SSRF | Request validation, authenticated proxy, DNS pinning, mixed-answer rejection, private IPv4/IPv6 denial | Kernel egress isolation and adversarial transport audit remain required |
| Isolation | Separate browser process tree, context/cookies, temporary staging directory | Per-session isolated filesystem mounts and OS process/resource sandbox |
| HITL | All mutations gated, exact action review, five-minute lifetime, single consumption, cancellation-safe uncertain receipt | Conservative policy intentionally does not infer that a page action is harmless |
| Tabs/frames | Popups registered, tab bounds, nested frame scopes, frame AX extraction, open shadow locators | Complex OOPIF/site-isolation combinations need broader cross-origin fixtures; closed roots require handoff |
| Recovery | Disconnect/page-crash detection, blank-worker reconstruction, monotonic generations, no replay | No automatic replay/restoration of credentials or transaction state; shared driver loss requires restart |
| Readiness | Target visibility/editability/trial click with bounded latency; READY/PARTIAL/TIMEOUT | Does not prove application-specific hydration beyond observable actionability |
| State/versioning | Monotonic snapshots, compound references, mutation/value/shadow fingerprints | Cannot guarantee atomic freshness against adversarial page JS |
| Verification | Explicit postconditions, rejects preexisting click/Enter evidence, typed uncertain outcomes | Remote business transaction finality is not inferred from a visual confirmation |
| Observation | 2,500-token compact snapshots with heading/header context and source URLs | Ambiguous/unnamed controls omitted; no lossless representation of arbitrarily large pages |
| Retrieval | Budgeted subtree inspection, streamed Markdown/JSON response, table/heading/list extraction | Extraction buffers a bounded subtree before streaming; merged cells/code whitespace may lose fidelity |
| API | Typed REST/OpenAPI, FIFO session serialization, idempotency, bounded bodies/queue/actions | Optional MCP transport is not implemented; use REST/OpenAPI |
| Tests | Real Chromium lifecycle, shadow, frame, extraction, action and network-policy tests | Full browser exploitation testing, chaos/stress/long-duration tests remain release gates |
| Benchmark | HTML/state tokens, dispatch/capture timings, process-tree CPU/RSS, concurrent capture | Synthetic local samples, not throughput or token-saving guarantees |
| Resources | Per-session sampled RSS threshold and cleanup, idle reaper, aggregate container caps | Sampling can overshoot; per-session cgroup/Job Object hard caps remain |
| Observability | Prometheus counters/histograms/gauge, content-free JSON audit events, health | Central log retention, alerts and tenant-scoped operations policies are deployment work |
| Container | Non-root multi-stage build, Chromium sandbox retained, Compose with resource/read-only restrictions | See VALIDATION.md for actual host verification; never disable sandbox to hide host incompatibility |
| Visual fallback | Canvas handoff signal; no pixel dependency in normal execution | CAPTCHA, WebGL and closed shadow content require a human/external tool |

The original requirement for fully deterministic action guarantees on arbitrary hostile websites cannot be honestly satisfied by DOM/AX observation alone. Agentra makes uncertainty explicit and avoids automatically replaying uncertain mutations. Production approval requires the deployment isolation and adversarial testing listed above.
