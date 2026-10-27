# Review handoff

This repository implements the AI Web Bridge MVP. No external AI provider is used. The user intends
to have Claude independently review the result; this file is a map for that review, not a claim of approval.

## Verification commands

```sh
python -m pip install -e '.[test]'
python -m pytest -q
python -m ruff check app tests examples
python -m ruff format --check app tests examples
python -m examples.demo
docker compose up --build
```

Optional: install `.[browser]`, install Chromium, and run tests with `BRIDGE_TEST_BROWSER=1`.

## Highest-value review areas

1. `app/utils/urls.py` and `app/services/fetcher.py`: DNS pinning, address classification, TLS SNI,
   per-origin connection pools, safe redirects, compression limits and proxy/cookie handling.
2. `app/services/browser.py`: resource routing, closed-proxy fallback, Chromium sandbox and browser
   resource limits. It is intentionally opt-in and not a hardened multi-tenant browser platform.
3. `app/services/manager.py` and `cache.py`: request-option cache keys, upstream cache-control handling,
   TTL eviction, concurrency and retained-memory behavior.
4. `extractor.py` and `cleaner.py`: extraction quality on real news, docs and product layouts, preservation
   of caveats/citations, long lists, multiple article roots and tables.
5. `formatter.py`: response budgets, duplicate JSON representations, token metric scope and query misses.
6. `core/logging.py`: body-size enforcement, error boundary, redaction and operational observability.

## Verified during implementation

- Python 3.13 host: 35 tests passed with the optional Chromium integration enabled.
- The Chromium test renders script-generated content and verifies a localhost fetch never reaches the gateway transport.
- Ruff lint and formatting checks were run; the final verification record is summarized in the delivery message.
- Offline fixtures demonstrate 46.78–61.71% main-text token reduction; a targeted query demonstrates 83.64%.
- Docker image built successfully on Python 3.12 and started through `docker compose up --build -d`.
- Container health check is healthy. Live smoke checks passed for the public example.com fetch,
  cache hit, Markdown extraction, metadata-endpoint SSRF denial, mixed-success batch and OpenAPI.
- The live example.com page was already compact: 43 estimated raw tokens to 39 returned (9.3%).
  This is separate from the larger fictional fixtures and illustrates why savings vary by page.

## Explicit scope gaps

- No Redis adapter, service authentication, per-tenant quotas, rate limiter, distributed workers or request coalescing.
- Memory cache has an entry cap, not a precise byte quota. DOM CPU/memory isolation needs stronger worker boundaries at scale.
- Token metrics exclude JSON overhead, links and metadata; section text is repeated alongside main_text.
- Query ranking is lexical, not semantic; generic overview questions have a deterministic fallback.
- Extraction uses one main/article root and within-page exact deduplication, not domain template learning.
- Browser redirect-heavy applications, authenticated sessions, POST-based APIs and full interaction are outside the MVP.
- No live internet performance guarantees or representative extraction quality benchmark are claimed.
- Dependency versions use bounded ranges rather than a fully locked transitive dependency set. The
  Docker smoke test used freshly resolved dependencies; the host suite used the installed environment.
- Batch request logs currently record aggregate timing; per-item diagnostic errors are in the batch response.
  Detailed timing fields on successful single requests depend on metadata being enabled.

Review should prioritize correctness and security over adding the future roadmap in this MVP.
