# AI Web Bridge

A deterministic, machine-oriented interface to public webpages. AI Web Bridge retrieves HTML,
removes presentation and boilerplate, extracts content blocks, ranks them against an optional query,
and returns structured JSON or Markdown. No LLM, API key, embedding model, or external AI service is required.

Human webpages mix useful information with menus, ads, account prompts and repeated templates.
The bridge reduces the content an agent must consume while preserving headings, lists, tables,
code examples, relevant links and source metadata. It is infrastructure, not a chatbot or an abstractive summarizer.

```text
AI Agent / LLM
      |
      v
+------------------+
|   AI Web Bridge  |
+------------------+
      |
      +--> Fetch
      +--> Parse
      +--> Clean
      +--> Rank
      +--> Compress
      |
      v
Structured Web Data
```

## Quick start

Requires Docker Desktop with its Linux engine running, or Python 3.12+.

```sh
docker compose up --build
```

The service binds to localhost only. Open [Swagger UI](http://localhost:8000/docs),
[ReDoc](http://localhost:8000/redoc), or [OpenAPI JSON](http://localhost:8000/openapi.json).
A generated schema snapshot is also included at `docs/openapi.json` for offline review.

```sh
curl http://localhost:8000/health
curl -X POST http://localhost:8000/v1/fetch \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","query":"What is this page about?"}'
```

PowerShell equivalent:

```powershell
Invoke-RestMethod http://localhost:8000/v1/fetch -Method Post `
  -ContentType application/json `
  -Body '{"url":"https://example.com","query":"What is this page about?"}'
```

Stop with `docker compose down`. The default image contains the HTTP implementation; Chromium is
deliberately an optional local installation, not part of the default container.

## Local development

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[test]'
# Copy .env.example to .env if you want to override defaults.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log
```

Use `python -m pytest`, `python -m ruff check app tests examples` and
`python -m ruff format --check app tests examples` for verification. Tests mock HTTP and DNS;
the default suite requires neither internet access nor Chromium.

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | Process liveness; not a check of upstream sites |
| `POST /v1/fetch` | Retrieve a public HTTP(S) page and extract information |
| `POST /v1/extract` | Process caller-supplied HTML without network requests |
| `POST /v1/batch` | Up to 20 URLs, in input order, with independent per-item errors |

Fetch request:

```json
{
  "url": "https://example.com/article",
  "query": "battery findings",
  "format": "json",
  "max_content_length": 12000,
  "include_links": true,
  "include_metadata": true,
  "render": "http"
}
```

`query` is optional. Without it, useful blocks are returned in document order. A specific query uses
BM25-style term scoring, heading matches and proximity. Generic overview questions return main content.
No lexical matches produce empty content with `metadata.query_matched=false`; the bridge does not invent an answer.
Scores are ranking scores, not probabilities. The length budget (100–100,000 characters) applies to
`content.main_text`, including headings and separators. The final block can be truncated.

`render` accepts `http` (default), `browser` (explicit opt-in), or `auto` (try browser when HTTP extraction
has fewer than 160 content characters and browser support is enabled). `include_metadata=false` sets metadata
to null; reduction statistics remain available. Unknown fields and invalid options return 422.

Response structure (abridged; complete real demo responses are in `examples/responses.json`):

```json
{
  "request": {"url": "https://example.com/news", "query": "battery findings"},
  "page": {"title": "Battery research findings", "language": "en"},
  "content": {
    "main_text": "Battery research findings\nA laboratory prototype retained 92% of its battery capacity after 1,000 charging cycles. The experiment used 24 cells under controlled temperatures.",
    "sections": []
  },
  "links": [],
  "metadata": {"fetch_method": "http", "cached": true, "metrics_scope": "main_text"},
  "optimization": {
    "estimated_raw_tokens": 269,
    "estimated_returned_tokens": 44,
    "estimated_tokens_saved": 225,
    "token_reduction_percent": 83.64
  },
  "actions": []
}
```

The abridged example omits sections and other metrics for readability. Actual JSON includes section text,
heading, relevance score, raw byte count, character counts, clean-token estimates and source metadata.
`actions` reserves an extension point; the MVP does not operate forms or buttons.

Raw HTML processing:

```sh
curl -X POST http://localhost:8000/v1/extract \
  -H 'Content-Type: application/json' \
  -d '{"html":"<main><h1>Results</h1><p>The battery retained 92% capacity.</p></main>","query":"battery"}'
```

An optional `url` on `/extract` resolves relative links; it does not trigger a fetch. Use `format: "markdown"`
on fetch or extract for a `text/markdown` response. Markdown contains title, source, selected text, links and
token estimates. Raw HTML is never returned.

```sh
curl -X POST http://localhost:8000/v1/batch \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://example.com","https://www.python.org/about/"],"query":"Python"}'
```

Batch always returns JSON with `results`; each item contains `url` and either `result` or `error`.
For Markdown batches, each successful `result` is a Markdown string. Batch concurrency shares the
fetcher's process-wide semaphore. A bad item does not cancel successful siblings.

Python client:

```python
import httpx

with httpx.Client(base_url="http://localhost:8000", timeout=30) as client:
    response = client.post("/v1/fetch", json={
        "url": "https://example.com", "max_content_length": 4000
    })
    response.raise_for_status()
    data = response.json()
    print(data["content"]["main_text"])
    print(data["optimization"])
```

Runnable clients: `examples/basic_request.py` and `examples/agent_request.py`.

## Request flow and module boundaries

1. FastAPI validates the request; middleware bounds the body and assigns a request ID.
2. The manager checks the final-response cache using normalized URL and every request option.
3. The HTTP fetcher validates DNS, pins the connection, checks robots policy and follows validated redirects.
4. The parser reads title, description, canonical URL, language, publication metadata and bounded JSON-LD.
5. The cleaner removes hidden elements, executable markup and likely boilerplate, retaining substantive notes.
6. The extractor scores DOM blocks using length, punctuation, link density, headings, semantic tags,
   ancestor class/ID and depth. Exact duplicate text is removed. Readability is an extraction fallback.
7. The relevance engine ranks query matches; the formatter selects blocks within the content budget.
8. The response includes sources, reduction metrics and cache state, then becomes eligible for TTL caching.

DOM processing runs in a worker thread under a concurrency limit. Async HTTP clients use origin-partitioned
connection pools: IP pinning cannot accidentally share a TLS session between unrelated virtual hosts.
Fetcher, cache, extractor, ranker and token estimator have replaceable interfaces. See `ARCHITECTURE.md`.

## Reduction measurements and demos

The estimator uses `ceil(UTF-8 byte length / 4)`. It is inexpensive and deterministic, but not an exact
tokenizer for any model. Raw tokens refer to parsed webpage text, not HTML markup or JavaScript bytes.
Clean tokens refer to extracted blocks before query filtering. Returned tokens refer to `main_text`.
Savings are `max(0, raw - returned)`; percentage reduction is `max(0, 100 * (1 - returned/raw))`.
Empty input denominators yield zero. HTTP `raw_bytes` counts compressed wire-body bytes; browser mode
reports the decoded resource-byte aggregate. These values are not directly comparable across strategies.

**Metrics do not count the full JSON payload.** JSON repeats content in `main_text` and `sections`, and
links/metadata add overhead. Agents should consume one content representation, or request Markdown.
Tiny pages can have little or no reduction; the service does not claim a universal savings rate.

Run reproducible fixture-based examples with no network or running server:

```sh
python -m examples.demo
```

| Fictional demo | Raw estimated tokens | Returned tokens | Reduction |
|---|---:|---:|---:|
| News article | 269 | 103 | 61.71% |
| Documentation, code and table | 171 | 91 | 46.78% |
| Encyclopedia-style article | 169 | 80 | 52.66% |
| Query: battery findings | 269 | 44 | 83.64% |

The same demo exercises batch and cache hits and regenerates `examples/responses.json`.
These small fixtures demonstrate behavior, not a representative web benchmark. Local processing and cache
responses are typically milliseconds on these fixtures; the <2-second/<100-ms goals are not service guarantees.

## Cache and configuration

Memory cache uses TTL, LRU eviction and defensive copies, bounded to 128 entries across documents,
parsed/cleaned representations and final responses. Keys are hashes; URL fragments are removed, query
strings are preserved. Requests with different queries can reuse a document and parsed blocks.
`cached=true` means some document or final-response data was reused. Responses declaring `no-store`,
`no-cache`, `private`, or setting cookies bypass document/parsed/final caching. Browser output is not cached.
Robots policy has a separate 5-minute bounded cache. Submitted HTML may be retained as processed text in memory.
Memory cache is per process and has no persistence, cache stampede coalescing or Redis adapter yet.

Settings are environment variables prefixed with `BRIDGE_`; see `.env.example`:

| Variable suffix | Default | Purpose |
|---|---:|---|
| `TIMEOUT` | 15 | HTTP operation deadline in seconds, including queue wait |
| `MAX_RESPONSE_BYTES` | 2000000 | Wire and decompressed size limit per response |
| `MAX_REQUEST_BYTES` | 3000000 | Incoming JSON body limit |
| `MAX_REDIRECTS` | 5 | Maximum HTTP redirect hops |
| `CONCURRENCY` | 8 | Per-process HTTP and processing limits |
| `CACHE_TTL` | 300 | Cache lifetime in seconds; 0 disables reuse |
| `CACHE_ENTRIES` | 128 | Maximum entries shared by pipeline stages |
| `RESPECT_ROBOTS` | true | Check robots.txt before every target/redirect |
| `BROWSER_ENABLED` | false | Allow browser rendering |
| `USER_AGENT` | AIWebBridge/0.1 | Identifier for requests and robots policy |

Compose forwards its listed settings; add any additional overrides to its `environment` section.

## Security and errors

- Only HTTP/HTTPS, ports 80/443, and URLs without userinfo are accepted.
- Every DNS result must be public. Loopback, private, link-local, multicast, reserved, shared-address,
  IPv4-mapped/transition IPv6 addresses and known Azure platform IP are blocked. Local hostnames are rejected.
- Connections use the validated IP, original Host header and original TLS verification name. DNS is not
  re-resolved between validation and connection. Each redirect repeats validation and robots checks.
- Environment proxies are ignored. Cookies and authentication from other requests are not forwarded.
- MIME allowlists, wire and decoded size limits, bounded gzip/deflate decoding, redirect limits,
  connect/read/total timeouts, and request body limits constrain untrusted input.
- Robots 404/410 allows fetching; denial, other errors or inability to verify fail closed. Crawl-delay and
  domain scheduling are not implemented. Respect target permissions and access policies.
- Structured logs include IDs, timings, hostname, sizes and cache state. Full URLs, query strings and
  page text are not logged. The default launch disables access logs. `/health` is liveness only.
- Retrieved content remains untrusted data, including possible prompt injection. The bridge extracts it;
  it does not certify truth, sanitize instructions for an LLM, or execute webpage code in HTTP mode.

Errors use `{"error":{"code":"BLOCKED_URL","message":"...","details":{}}}`. Codes include
`INVALID_URL`, `BLOCKED_URL`, `FETCH_TIMEOUT`, `FETCH_FAILED`, `UNSUPPORTED_CONTENT_TYPE`,
`CONTENT_TOO_LARGE`, `PARSE_FAILED`, `NO_CONTENT`, `RATE_LIMITED`, `ROBOTS_DENIED`,
`INVALID_REQUEST`, `BROWSER_DISABLED`, `BROWSER_UNAVAILABLE`, `REQUEST_TIMEOUT`, and `INTERNAL_ERROR`.
Validation errors expose field locations, not submitted HTML or sensitive query values.

The MVP has no authentication, tenant isolation, service-level rate limiting or distributed admission control.
Do not expose it publicly without a gateway providing those controls and network-level egress restrictions.
Container defaults use a non-root user, read-only filesystem, dropped capabilities and a localhost binding.
Entry limits are not a precise cache byte quota; set memory limits and tune cache capacity for your workload.

## Optional browser

```sh
python -m pip install -e '.[browser]'
python -m playwright install chromium
# Set BRIDGE_BROWSER_ENABLED=true and restart the service.
```

One render runs at a time with a fresh sandboxed Chromium context. GET requests for documents, scripts,
styles and data pass through the same validated HTTP gateway. Images, POSTs, service workers and WebSockets
are blocked. A closed local proxy is a fallback for unrouted traffic. Rendering caps requests at 40, decoded
resource bytes at three times the response limit and DOM size at the response limit. Use a dedicated,
restricted worker/container for real untrusted browsing; interception is not a substitute for OS isolation.

Browser mode is intentionally limited: no logins, persistent sessions, downloads, full automation or
interactive actions. Redirected subresources/navigation, CORS-heavy applications, live connections and
sites that need POST requests may fail. The default Compose image does not include Chromium.

Run its opt-in integration test after installation:

```sh
BRIDGE_TEST_BROWSER=1 python -m pytest tests/test_browser.py
```

PowerShell: `$env:BRIDGE_TEST_BROWSER='1'; python -m pytest tests/test_browser.py`.

## Limitations and roadmap

Extraction is heuristic: unusual layouts, multiple competing article roots, CSS-only visibility and
cross-page repeated templates can confuse it. Lexical relevance has no semantic understanding, stemming
or multilingual tokenization. Chunk boundaries may split prose/code; no generated summaries are produced.
The selected source remains authoritative for caveats that a narrow query may omit.

Recommended next steps:

1. Independent SSRF/browser review and a broader extraction quality corpus, followed by load benchmarks.
2. Authentication, quotas, byte-budgeted cache, request coalescing, per-domain scheduling and Redis.
3. Better chunk boundaries, structural table output and exact model-tokenizer adapters.
4. Optional embedding or LLM rerankers behind the existing ranker boundary, with deterministic fallback.
5. MCP and Python/JavaScript SDKs, then crawling/indexing, freshness and change detection.
6. Versioned machine-web entities, relationships and actions after the extraction API stabilizes.

## Project tree

```text
ai-web-bridge/                 # this repository's root
├── app/
│   ├── main.py
│   ├── api/routes.py
│   ├── core/{config,exceptions,logging}.py
│   ├── models/{request,response}.py
│   ├── services/
│   │   ├── manager.py
│   │   ├── fetcher.py
│   │   ├── browser.py
│   │   ├── parser.py
│   │   ├── cleaner.py
│   │   ├── extractor.py
│   │   ├── relevance.py
│   │   ├── formatter.py
│   │   ├── cache.py
│   │   └── robots.py
│   └── utils/{urls,text,tokens}.py
├── tests/test_{api,browser,cache,cleaner,extractor,fetcher,formatter,relevance,robots}.py
├── examples/
│   ├── basic_request.py
│   ├── agent_request.py
│   ├── demo.py
│   ├── pages/{news,documentation,encyclopedia}.html
│   └── responses.json
├── docs/openapi.json
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── ARCHITECTURE.md
├── REVIEW.md
└── README.md
```
