# Local validation

## Progress audit — 10 November 2026

Docker Desktop's engine was stopped at the start of the audit. Restored the `mhp` project and verified healthy status plus the authenticated live API navigation/snapshot smoke test. The existing 42-test suite passed in 45.11 seconds; the lifecycle suite then passed all five tests, including a new actual OS-level browser-process kill test (43 distinct tests now). Strict mypy passed all 14 modules. One upstream TestClient deprecation warning remains. Added `restart: unless-stopped`; this restarts the container when Docker runs, but cannot start Docker Desktop itself.

The new process-kill test checks the worker PID creation time before termination, verifies the other session remains usable, and verifies blank-session recovery. Production completion is still gated by per-session kernel-enforced resource/filesystem/network isolation and sustained adversarial testing; earlier successful smoke tests do not remove these requirements.

## Real-world reading fix

42 tests passed in 31.79 seconds; mypy passed 14 modules. A live Bing search for `gold rate Hyderabad today` returned results through Agentra after replacing snapshot-dependent document extraction with fresh read-only evaluation. Goodreturns' Hyderabad page was fetched and read with title/date 7 November 2026; it quoted 24K INR 14,357/g, 22K INR 13,160/g and 18K INR 10,768/g at the observation time. Prices are source-specific, time-sensitive observations, not fixed fixtures. Google's automation challenge was previously reproduced; new classification returns HUMAN_REQUIRED for its challenge URL/content. Continuous-mutation regression proves reads can complete while the DOM changes. Navigation and content availability are explicitly separate from task completion.

## Docker project mhp

Built and launched `mhp-agentra-1` through Docker Compose. The live API smoke test passed health, authenticated session creation, authorization gating, real HTTPS navigation to example.com, semantic state capture and cleanup. Chromium sandboxing is enabled. Playwright v1.58.0's official seccomp profile enables user namespaces; `no-new-privileges` is retained. Dropping every capability prevented Chromium startup on this host, so the service uses Docker's default capability bounding set while running as non-root. Read-only filesystem, temporary mounts, memory/PID limits and localhost-only publishing remain enabled. This validates the tested workflow, not perfection or all production security requirements.

## Hardening and retrieval phase

Windows, Python 3.13.3, pinned Playwright 1.58.0: 39 tests passed in 18.01 seconds. Strict mypy passed 13 source modules. The public HTTPS proxy smoke test successfully navigated to example.com and returned VERIFIED. Focused API tests passed after the health endpoint update. Tests requiring tokenizer/browser assets ran outside the restricted execution runner; its isolated cache cannot resolve/download the vocabulary.

Measured synthetic run (101 buttons; cumulative live workers):

| Workers | Capture seconds | Verified action seconds | HTML tokens | State tokens | Process-tree RSS bytes | Cumulative CPU seconds |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.372 | 0.491 | 847 | 2435 | 422297600 | 3.219 |
| 2 | 0.732 | 0.892 | 847 | 2435 | 754708480 | 5.578 |
| 3 | 0.639 | 0.850 | 847 | 2435 | 1088614400 | 8.094 |

Three concurrent captures completed in 0.859 seconds. These are single-run measurements, not throughput guarantees. This small fixture still uses more tokens in structured state than raw HTML; no token-saving claim is supported.

## Live browser mode

25 tests passed in 13.60 seconds; strict mypy passed eight source modules. The headed offline demo ran successfully with real Chromium: TYPE and CLICK returned VERIFIED, the expected confirmation appeared, and the worker closed cleanly. One upstream TestClient deprecation warning remains.

## Phase 2

Python 3.13.3, pinned Playwright 1.58.0, Windows: 21 tests passed in 26.38 seconds. Strict mypy passed all seven source modules. New real-browser tests cover separate workers, disconnect recovery, cancellation of pending approvals, historical idempotency, tenant ownership, stale references across recovery, cleanup and late events. One upstream httpx TestClient deprecation warning remains. OS-level process kills, cgroup limits and container execution have not been validated.

## Phase 1 baseline

Final regression tests: Python 3.13.3, Playwright 1.63.0, Windows. 16 passed in 13.12 seconds, including frame-specific AX capture. Strict mypy: all seven source modules passed using the project virtual environment (Playwright 1.58.0).

Pinned-environment verification: Playwright 1.58.0 and its Chromium also passed all 16 tests in 11.25 seconds. The test client emitted an upstream httpx deprecation warning.

Synthetic benchmark with 100 buttons, cumulative live sessions:

| Sessions | Snapshot seconds | HTML tokens | State tokens | Process-tree RSS bytes |
| --- | --- | --- | --- | --- |
| 1 | 1.365 | 824 | 2426 | 428302336 |
| 2 | 1.207 | 824 | 2426 | 525008896 |
| 3 | 0.634 | 824 | 2426 | 618684416 |

This fixture has little HTML overhead. Structured addressing increases token use here; no token savings demonstrated. These are individual local runs, not statistical performance guarantees. Docker has not been built or validated.
