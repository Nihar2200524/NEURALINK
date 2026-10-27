# Architecture decisions

The bridge is a single async service, independent of AI providers. The request manager composes fetcher,
parser, cleaner, extractor, ranker, formatter and cache. CPU-bound DOM work runs in a worker thread.
Models describe data at module boundaries; fetched documents never expose HTTP client objects.

HTTP connections will use validated, pinned public IP addresses with the original Host header and TLS
server name. Redirects are processed manually and revalidated. Environment proxy settings are ignored.
Browser rendering is optional and uses an HTTP interception gateway so browser subrequests use the
same network policy. Deployment must additionally restrict network egress and isolate browser workers.

Memory caching is bounded and TTL based. Separate document and final-response keys allow query reuse.
Cache is process-local. A cache protocol permits a shared implementation later.

Connection pools are partitioned by original origin, capped at 32 retained clients per fetcher with
two idle connections each; additional origins use temporary clients. A shared semaphore bounds active
HTTP requests. Cookies are explicitly omitted. Robots checks use a separate bounded fetcher to avoid
recursive acquisition deadlocks. Cache misses are not coalesced in this MVP.

Content extraction uses DOM heuristics with readability as a fallback. Relevance uses deterministic
term scoring. Token counts are explicitly estimates, not billing measurements. Returned-token metrics
measure main content only, not JSON envelopes or repeated section representations.

The HTTP strategy uses the documented [HTTPX SNI extension](https://www.python-httpx.org/advanced/extensions/)
to retain hostname verification while connecting to a pinned address. Browser interception follows
[Playwright's network routing guidance](https://playwright.dev/python/docs/network), including disabling
service workers. Browser mode remains experimental and needs network-level isolation in deployment.

## Review boundaries

- URL normalization does not reorder query parameters: ordering can be meaningful to upstream applications.
- All resolved addresses must be safe, even when the selected address is public.
- No URL from HTML metadata is fetched automatically; links and canonical URLs are informational only.
- `/extract` permits a source URL for resolving relative links but performs no network requests.
- Main extraction prioritizes the largest semantic main/article root, then scored blocks. It is not a
  trained relevance classifier or a comprehensive cross-site template detector.
- Core output never requires an LLM. Future semantic processors must sit after structured extraction.
- JSON-LD is bounded by script count and size and remains untrusted metadata.
- Browser installation is optional and outside the default image, preserving a small HTTP service.
