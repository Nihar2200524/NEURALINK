# Agentra runtime and trust boundaries

```mermaid
sequenceDiagram
    participant Agent
    participant API
    participant Session
    participant Approver
    participant Chromium
    participant Proxy
    Agent->>API: Bearer token + action + idempotency key
    API->>API: Size/schema/ownership validation
    API->>Session: FIFO lock + lifecycle check
    Session->>Session: Snapshot and mutation freshness checks
    Session-->>Agent: AUTHORIZATION_REQUIRED (five-minute pending action)
    Approver->>API: Review exact pending action using separate credential
    Approver->>API: Authorize pending action ID
    API->>Session: Consume approval; reserve uncertain-outcome receipt
    Session->>Session: Recheck freshness and precondition
    Session->>Chromium: Locator actionability + action
    Chromium->>Proxy: HTTP request or HTTPS CONNECT
    Proxy->>Proxy: Resolve all DNS answers; reject nonpublic IPs
    Proxy->>Proxy: Connect to validated numeric IP
    Session->>Chromium: Assert observable changed postcondition
    Session->>Chromium: CDP AX metadata + scoped semantic state
    Session-->>Agent: Typed receipt + new snapshot
```

## Processes and ownership

One API/Playwright driver controls one separate Chromium process tree per session. Each browser owns one nonpersistent context and its own staging directory. Authentication maps high-entropy bearer credentials to tenants; session lookup deliberately returns 404 for wrong owners. One FIFO asyncio lock serializes session commands; the waiting queue is capped at 32 and waits at most 30 seconds. Requests are bounded to 256 KiB. Session, tab, approval and idempotency limits prevent ordinary unbounded growth.

Browser disconnects or renderer crash events invalidate all references and pending approvals. Recovery is explicit and serialized: stop the old worker, launch a blank new one, increment generation and snapshot version. Historical terminal idempotency receipts remain; uncertain actions are never replayed. Pending actions require a fresh proposal after recovery. Session deletion closes context/browser, cancels background work and removes staging files. SIGTERM invokes the FastAPI lifespan shutdown.

## Network boundary

Chromium uses a local authenticated forward proxy with implicit loopback bypass disabled. Every upstream connection resolves DNS once, rejects any non-global answer (including IPv4-mapped private IPv6), and connects to the resulting numeric IP. Only ports 80/443 are allowed. Redirects cannot move an existing TCP connection to another IP: a new destination requires another validated proxy connection. HTTPS uses CONNECT without TLS interception. Proxy streams have bounded headers, connection count, handshake and lifetime limits. Service workers and WebSockets are disabled; QUIC and non-proxied WebRTC UDP are disabled by launch flags.

This is application-level mediation, not a kernel network sandbox. A Chromium exploit, unsupported transport, host-level traffic or proxy configuration regression needs independent OS firewall/network-namespace containment. Loopback proxy credentials are ephemeral and never exposed in the API. Raw HTTP relay binds a connection to its validated upstream; the proxy does not claim to be a complete HTTP security gateway or malware filter.

## Observation and action semantics

AX metadata supplies scoped role/name references. Ambiguous or unnamed controls are omitted rather than guessed. Document references support whole-frame Markdown extraction. Snapshot IDs increase monotonically; DOM mutation epochs, form-value hashes, open-shadow hashes and frame URLs detect ordinary changes. This is not a security guarantee against malicious scripts that can tamper with observation code. Check-to-dispatch races remain possible on actively mutating pages.

Snapshot READY means capture stability. `/readiness` instead checks the specific locator with visibility/editability or a trial click; PARTIAL indicates an attached target that did not become actionable before its deadline. No network-idle requirement is used. Click and Enter actions require explicit evidence that was not already true before dispatch. Verified means the supplied observable predicate held, not proof of a remote business transaction. Timeout/failed receipts must not trigger automatic replay.

All page data is structurally labeled `untrusted_web_payload`; it must never be promoted into agent instructions. Markdown responses carry the equivalent trust header. Input values are omitted from raw extraction. Canvas requires human review. Closed shadow DOM, image CAPTCHA and WebGL controls require an explicit external handoff; no stealth or automatic CAPTCHA bypass exists.

## Resources and deployment

The resource monitor discovers each Chromium worker PID using read-only CDP metadata, tracks its creation time, and samples process-tree RSS each second. Exceeding the configured threshold closes the worker and records MEMORY_LIMIT. Transient spikes can exceed the threshold before sampling; this is not a hard allocator cap. Compose supplies an aggregate container memory/PID cap. Hard per-session cgroups/Windows Job Objects and isolated mounts remain deployment work.

The non-root image retains Chromium sandboxing. Host user namespaces/seccomp must permit it; do not use `--no-sandbox` or privileged mode to hide failures. The single in-memory API worker cannot be horizontally scaled without tenant/session routing and external state. Secrets require an external secret store and HTTPS termination for remote deployment. Fixed bearer/approver credentials need rotation and deployment access controls.
