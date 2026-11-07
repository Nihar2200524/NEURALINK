# Local validation

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
