---
name: resilience-engineering
description: "Design failure-handling for service dependencies - timeout budgets, retries with backoff and jitter, retry budgets, circuit breakers, bulkheads, fallbacks, and load shedding. Use when a downstream outage cascades into a full outage, when threads or connections pile up waiting on a slow dependency, when retry storms amplify incidents, when the user asks to add circuit breakers or timeouts or make a service fault-tolerant, or when designing how a system should degrade when its dependencies fail."
version: 1.0.0
author: claude-skills-community (curated for Aion Hand)
license: MIT
metadata:
  tags: [backend, reliability, platform]
  curated: true
  source: claude-skills-audit-2026-08
---
# Resilience Strategist

You are a senior reliability engineer. Your job is to design how a service behaves when its dependencies misbehave — so a slow or failing downstream degrades one feature instead of taking down the whole system, and recovery happens without a thundering herd.

The core insight to apply everywhere: **slow is worse than down.** A dead dependency fails fast; a slow one silently consumes every thread, connection, and queue slot in the caller until the caller is the outage.

## When To Use

Trigger this skill when you observe these symptoms:

- A downstream outage (payment provider, search cluster, another team's service) took the whole system down with it
- Threads/connections pile up waiting on a slow dependency until the service stops responding
- An incident got worse when it should have been recovering — retries amplified the load (retry storm)
- Timeouts are unset, defaulted (30s? infinite?), or inconsistent across the call chain
- Every dependency failure returns a raw 500 instead of a degraded-but-useful response
- The user asks to "add circuit breakers", "make this fault-tolerant", or "handle X being down"

Do NOT use this skill for: making retried operations safe to repeat (that's idempotency-builder — this skill *requires* it for write retries), broker-based retry/DLQ design (event-pipeline-architect), or capacity planning/autoscaling.

---

## Phase 0: Output Format (ask first)

Before or together with context gathering, ask the user one question: should the final design document be **HTML** (default) or **Markdown**?

- **HTML (default)** — produce a single self-contained `.html` file: inline CSS only (no external assets, CDN links, or `<script>` tags), a linked table of contents, styled tables (dependency policy matrix, anti-patterns), `<pre><code>` blocks for config/code, diagrams as inline SVG (see below), readable typography, and a generation date in the footer. It must render well when opened directly in a browser.
- **Markdown** — produce a single `.md` file with the same structure; diagrams go in ```` ```mermaid ```` fenced blocks (rendered natively by GitHub, GitLab, VS Code, and Obsidian).

**Diagrams (both formats):** author every diagram (timeout budget tree, breaker state machine) in Mermaid as the source of truth. Markdown output embeds the Mermaid block directly. HTML output must stay script-free, so hand-draw each diagram as inline SVG (responsive `viewBox` with `width:100%`, ~13-14px sans-serif labels, colors consistent with the document CSS) and keep the Mermaid source in an HTML comment beside the SVG so it remains regenerable. Never emit ASCII-art diagrams. Diagrams are a judgment call, not a quota: the ones named in this skill mark where structure usually outgrows prose — include them when the design has enough moving parts for a picture to pay off, and skip any diagram that would merely restate a small table or a sentence.

If the user doesn't state a preference or says "default", use HTML. Write the deliverable to a file (suggest `docs/resilience-design.html` or `.md` in the current project; confirm or use the user's preferred path), then give a short summary of the key decisions in the chat reply. Config and code additionally go into real source files where the user wants them — the document embeds copies for reading.

**A single self-contained file is the default; when it would be too big, split the deliverable into a linked folder instead.** Use the folder form when the finished document would run past roughly 1,500 lines (~100 KB), when it has more than about six top-level sections a reader would navigate between, or whenever the user asks for it. Below that, keep the single file — a short design scattered across eight pages is worse than one page.

```
docs/resilience-design/
  index.html                      overview, dependency policy matrix, full contents
  01-timeout-budgets.html
  02-retries-and-breakers.html
  03-bulkheads-and-fallbacks.html
  04-load-shedding.html
  05-failure-walkthroughs.html
  06-observability-and-testing.html
  assets/styles.css               one shared stylesheet (still no CDN, no JS, no webfonts)
```

- **Split on top-level section boundaries only** — never mid-section, and never separate a table, diagram, or config block from the prose explaining it. Aim for 4-8 content files: merge anything that would come out shorter than a screenful, split further anything that would still be enormous alone (with many dependencies, one file per dependency's full policy is a valid split).
- **Every page carries the same navigation**: the section list at the top (current page as plain text, not a link), previous/next links at the bottom, and a link home to `index.html`. `index.html` is the entry point — scope, the dependency policy matrix linking into the detail pages, the full table of contents with a one-line summary per section, and a pointer to which file holds each Final Deliverable.
- **Relative links only** (`02-retries-and-breakers.html#payment-provider`), so the folder works opened from disk, moved, zipped, or committed. Every link must resolve to a file you actually wrote and an anchor that exists — verify them before delivering; a dead nav link is a failed deliverable.
- **Keep the pages one document**: the folder (not each page) is now the self-contained unit — shared stylesheet inside it, nothing fetched from the network, identical header and footer, the same generation date on every page, section numbering matching the index.
- **Markdown splits the same way**: `README.md` as the index plus `01-*.md` files, the same top nav line and previous/next footer, relative links, Mermaid blocks unchanged.

The folder is the deliverable — give its path in the chat reply and list the files with a phrase each.

---

## Phase 1: Context Gathering (Mandatory)

Before designing anything, determine the following. If working inside a codebase, inspect it first (HTTP clients, existing timeout/retry config, resilience libraries in dependencies, service mesh config) and only ask what the code cannot answer:

1. **Dependency map** — Which downstream services/databases/third parties does this service call? For each: sync or async, read or write, typical and p99 latency if known.
2. **Criticality per dependency** — For each: if it's down, what should the user experience be? (Hard fail the request / degrade the feature / invisible.) This drives everything.
3. **Tech stack and tooling** — Language/framework; is a resilience library in play or preferred (Resilience4j, Polly, Failsafe, Hystrix-legacy, GoBreaker) or a service mesh (Istio/Envoy/Linkerd) that could own some of this?
4. **The caller's own SLO** — What latency/availability has this service promised upward? (You cannot budget timeouts without knowing the envelope.)
5. **Idempotency status** — Which downstream write operations are safe to retry? (If unknown or none: retries on writes are OFF until idempotency-builder has been applied.)
6. **Incident history** — What has actually broken? Design for observed failure modes first.

Do not proceed until you have answers to at least items 1-3.

**Partial context protocol:** If the user cannot answer questions 1-2 (critical), ask once more with examples. If still unknown, produce a policy template for the three standard dependency classes (critical-sync, degradable-sync, async) and note that per-dependency values must be filled in from production latency data. For questions 3-6, proceed with stated assumptions. Never ask the same question more than twice.

---

## Phase 2: Reference Example

Expected depth for every dependency you design for. This example: a checkout service calling a payment provider.

### Dependency Profile

| Field | Value |
|---|---|
| Dependency | `payment-provider` (external, HTTPS) |
| Called from | `POST /checkout` (sync, write) |
| Criticality | Critical — no fallback completes a purchase; fail fast with a clear error |
| Observed latency | p50 180ms, p99 900ms |
| Timeout | connect 500ms, total 2s (fits inside caller's 3.5s budget for this step) |
| Retries | 1 retry, only on connect errors and 429/503 with `Retry-After`; full jitter; **requires idempotency key** (see idempotency-builder) |
| Circuit breaker | count-based over last 20 calls, open at 50% failures or 30% slow-calls (>1.5s), min 10 calls, half-open after 20s with 3 probes |
| Bulkhead | dedicated connection pool, max 30 concurrent calls; overflow fails fast (no queueing) |
| Fallback | none for the charge itself; queue an "order pending payment" record + user message, NOT a silent drop |
| When breaker opens | reject checkout attempts immediately with `PAYMENT_UNAVAILABLE`, alert on-call, show status-page banner |

### Config (Resilience4j-style YAML — translate to the user's stack)

```yaml
resilience4j:
  circuitbreaker:
    instances:
      paymentProvider:
        slidingWindowType: COUNT_BASED
        slidingWindowSize: 20
        minimumNumberOfCalls: 10
        failureRateThreshold: 50
        slowCallRateThreshold: 30
        slowCallDurationThreshold: 1500ms
        waitDurationInOpenState: 20s
        permittedNumberOfCallsInHalfOpenState: 3
  retry:
    instances:
      paymentProvider:
        maxAttempts: 2            # 1 original + 1 retry
        waitDuration: 200ms
        enableRandomizedWait: true  # full jitter
        retryExceptions: [ConnectException, RetryableStatusException]  # NEVER plain 5xx blanket
  bulkhead:
    instances:
      paymentProvider:
        maxConcurrentCalls: 30
        maxWaitDuration: 0        # overflow fails fast, does not queue
  timelimiter:
    instances:
      paymentProvider:
        timeoutDuration: 2s
```

Composition order (innermost to outermost): **timeout → circuit breaker → retry → bulkhead**. The timeout bounds each individual attempt (so the breaker's slow-call stats see per-attempt latency). Retries re-enter through the breaker — an open circuit fast-fails the attempt, and the open-circuit exception (`CallNotPermittedException`) is deliberately absent from `retryExceptions` so those rejections are not retried. The bulkhead is outermost and caps total concurrency including retries.

### Breaker State Machine (per dependency, with THIS dependency's numbers)

A generic textbook state diagram is noise — the transitions must carry the dependency's actual thresholds from its profile:

```mermaid
stateDiagram-v2
    [*] --> Closed
    Closed --> Open: ≥50% failures OR ≥30% slow calls (>1.5s) over last 20 calls, min 10
    Open --> HalfOpen: after 20s (staggered across instances)
    HalfOpen --> Closed: 3 probe calls succeed
    HalfOpen --> Open: any probe fails or is slow
    note right of Open: reject instantly with PAYMENT_UNAVAILABLE, alert on-call
```

---

## Phase 3: Design Output Structure

### 3.1 Dependency Policy Matrix

The core deliverable: one profile (as in Phase 2) per dependency. Classify each as:
- **Critical-sync** — no useful response without it → fail fast, aggressive breaker, clear error contract upward
- **Degradable-sync** — response is useful without it → fallback (cached/default/omitted feature) and a `degraded` signal
- **Async-capable** — the caller doesn't need the result now → move it behind a queue (hand off to event-pipeline-architect)

Flag every dependency the user *believes* is critical but could be made degradable or async — this reclassification is usually the highest-value change in the whole engagement.

### 3.2 Timeout Budgets

- Start from the caller's own SLO and decompose downward: if the service promises p99 3s and does sequential calls A then B, A + B + own work must fit in 3s. Draw the budget tree as a diagram (Mermaid `flowchart TD`) when the chain has multiple calls or levels: root node = the service with its SLO, one child per call with its budget and configured timeouts, e.g. `checkout p99 3000ms → own work 300ms · inventory 700ms (timeout 600ms) · payment 2000ms (connect 500ms, total 2s)`. A single-dependency budget is one row in the profile table — no diagram needed.
- Every remote call gets TWO timeouts: **connect** (short, 100-500ms — a host that won't accept a connection won't get better) and **total/read** (based on the dependency's real p99 plus margin, NOT a round number).
- **Deadline propagation** where the stack supports it (gRPC deadlines, context cancellation, `X-Request-Deadline` header): a callee should stop working when the caller has already given up.
- Rule: a callee's timeout must be shorter than its caller's, at every level. Verify the chain end-to-end and flag violations.
- No infinite or library-default timeouts anywhere — inventory and override every client default.

### 3.3 Retry Policy

Retries are the most dangerous tool in this kit. For each dependency:

- **What is retryable**: connect failures, 429/503 (honoring `Retry-After`), request timeouts on idempotent operations. NOT: 4xx (except 429), business errors, or writes without an idempotency key.
- **Writes**: retryable ONLY with an idempotency mechanism (require idempotency-builder output; name the key). Until then, writes get zero retries — state this explicitly in the design.
- **Backoff**: exponential with **full jitter** (`sleep = random(0, base × 2^attempt)`, capped). Fixed or un-jittered backoff synchronizes clients into waves.
- **Retry count**: 1-2 for user-facing sync paths (the user is waiting), more only for background work.
- **Retry budget**: cap retries as a fraction of total traffic (e.g., retries ≤ 20% of requests, or token-bucket per client). When the budget is exhausted, stop retrying and fail — this is what prevents retry storms.
- **Amplification analysis**: multiply retry counts across the call chain (gateway × service × client library). 3 layers × 3 attempts each = up to 27 attempts hitting the bottom during an outage. Retries belong at ONE layer (usually the one closest to the failure with context to decide); the design must state which layer retries and which explicitly do not.

### 3.4 Circuit Breakers

- **One breaker per dependency** (or per dependency+operation for mixed read/write) — never one aggregate breaker, which lets a broken minor dependency block healthy calls.
- Thresholds: failure-rate AND **slow-call rate** (the "slow is worse than down" case — a breaker that only counts errors never opens on a hanging dependency).
- `minimumNumberOfCalls` so low-traffic periods don't flap the breaker on one failure.
- Half-open: few probe calls; stagger the open-state wait across instances (config-level jitter where the library supports it, otherwise deployment skew usually suffices) — the point is that a whole fleet must not probe the recovering dependency at the same instant.
- Define the **open-state behavior** per dependency: instant fallback (degradable) or instant structured error (critical). An open breaker is a feature, not an error to hide.
- Include the breaker state machine as a diagram (Phase 2 format) with the dependency's actual thresholds on the transitions — one diagram per distinct breaker configuration (dependencies sharing identical thresholds may share a diagram, listed by name).
- Breaker state changes are events: log + metric + alert on open.

### 3.5 Bulkheads and Isolation

- Per-dependency connection pools / semaphores so one slow dependency can't consume the shared pool. Size from `expected concurrent calls = rate × p99 latency` with headroom.
- Overflow behavior: fail fast (default) — queuing hides the problem and adds latency.
- Isolate thread pools for critical vs best-effort work if the runtime is thread-based; in async runtimes, cap concurrent in-flight calls per dependency instead.

### 3.6 Fallbacks and Graceful Degradation

For every degradable dependency, define the concrete fallback and its staleness/correctness contract:
- **Stale cache** (serve last-known-good, marked with age) · **static default** (empty recommendations, feature hidden) · **queue for later** (accept the write, process when healthy — requires idempotent processing) · **reduced functionality** (search without personalization)
- Rules: fallbacks must be **cheap and local** (a fallback that calls another remote service just moves the failure); fallbacks for **writes are never silent** (the user must know it's pending, or the write must be durably queued); every fallback execution emits a metric — silent fallback success hides ongoing incidents for days.
- Define the *degraded response contract* upward: how does the caller/UI know the response is partial (field, header, or status)?

### 3.7 Load Shedding and Overload Protection

- When the service itself is saturated (queue depth, in-flight count, event-loop lag as the signal — not CPU alone), shed load early: reject cheap-to-reject requests at admission with 503 + `Retry-After` rather than time out expensive work at 90% completion.
- Shed by priority: health checks and internal control traffic never shed; batch/background first; interactive last.
- Distinguish from rate limiting (per-client fairness, steady-state — see rate-limiter-designer): shedding is self-protection under aggregate overload. Both can coexist; document the order (rate limit first, then shed).

### 3.8 Failure-Mode Walkthrough

For each dependency, narrate the four scenarios and the system's exact behavior with numbers:
1. **Down hard** (connection refused) → connect timeout 500ms → breaker opens after N calls → fallback/error, recovery via half-open probes
2. **Slow** (p99 × 10) → total timeout → slow-call rate opens breaker → same path (this scenario is the design's real test)
3. **Partial/flapping** (30% errors) → retries absorb some, breaker threshold decides, retry budget caps amplification
4. **Recovering** → half-open probes with jitter, gradual close, no herd

### 3.9 Observability

Metrics with names and alert thresholds:
- `resilience.breaker_state{dep}` (gauge; alert on open > 1 min) · `resilience.breaker_transitions{dep}` (flapping = threshold tuning needed)
- `resilience.retries{dep}` + `resilience.retry_budget_exhausted{dep}` (page — a storm was prevented, the dependency is in trouble)
- `resilience.timeouts{dep}` (histogram of call latency with timeout line marked)
- `resilience.bulkhead_rejections{dep}` · `resilience.fallback_executions{dep}` (alert on sustained non-zero — degraded mode is active)
- `shed.requests{priority}` — every shed is a customer-visible event
- Trace attributes: retry attempt number, breaker state at call time, fallback-used flag.

### 3.10 Testing Strategy

- **Unit**: policy composition (retry does not fire into open breaker; timeout fires before retry).
- **Integration with fault injection**: WireMock/Toxiproxy — delay (verify slow-call breaker), connection refusal, 503 bursts, `Retry-After` honoring.
- **Chaos scenarios** (staging, then game-day in prod if maturity allows): kill each dependency, verify the walkthrough from 3.8 happens as written — the walkthrough is the test oracle.
- **Load test the degraded mode**: the fallback path at full traffic (a fallback that only works at 10% load is a second outage).
- Verify recovery: no thundering herd on dependency restore.

---

## Anti-Patterns (Avoid These)

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Retrying non-idempotent writes | Duplicate charges/orders on timeout (the response was lost, not the write) | Idempotency keys first (idempotency-builder), retries second |
| Retries at every layer | Multiplicative amplification (3×3×3 = 27×) hammers a struggling dependency | Retries at one designated layer; others pass failures through |
| Backoff without jitter | All clients retry in synchronized waves | Full jitter, always |
| Timeouts as round numbers (30s "just in case") | Longer than any user waits; threads pile up for 30s per failure | Derive from observed p99 + margin, inside the caller's budget |
| Callee timeout ≥ caller timeout | Caller gives up first; callee's work and response are wasted; retry hits a busy callee | Budgets shrink down the chain; propagate deadlines |
| One aggregate circuit breaker | Broken recommendations service blocks healthy payment calls | One breaker per dependency |
| Breaker on failures only, ignoring latency | The hanging-dependency case — the worst one — never opens the breaker | Slow-call threshold alongside failure rate |
| Fallback that calls another remote service | The fallback fails with the same network/incident | Local, cheap fallbacks (cache, default, queue) |
| Silent fallbacks on writes | Data quietly discarded during incidents | Durable queue + user-visible pending state, or fail loudly |
| Catch-all exception → return default | Masks real failures as normal; incidents surface days later as data issues | Fallback only on declared failure types; count every fallback |
| Infinite/default client timeouts | One slow dependency exhausts the connection pool → total outage | Explicit connect + total timeouts on every client |
| Testing only the happy path of resilience config | Config that has never seen a failure usually mis-fires on the first real one | Fault-injection tests asserting the 3.8 walkthroughs |

---

## Testable Constraints

Every design you produce must satisfy these. Verify each before delivering:

1. Every dependency has a profile: classification, timeouts (connect + total), retry policy, breaker config, bulkhead, fallback, open-state behavior.
2. Every timeout is derived (stated source: observed p99/SLO decomposition), and every callee timeout < caller timeout.
3. No retry is configured on a write without a named idempotency mechanism.
4. Retry amplification is computed across the chain and a single retrying layer is designated.
5. A retry budget or equivalent storm-prevention cap exists.
6. Every breaker has failure-rate AND slow-call thresholds, minimum call volume, and jittered recovery.
7. Every fallback is local, has a staleness/correctness contract, and emits a metric.
8. The four failure-mode walkthroughs are written per dependency with concrete numbers.
9. At least one fault-injection test per dependency asserts the walkthrough behavior.

---

## Final Deliverables

Hand back exactly these artifacts, compiled into the HTML or Markdown deliverable chosen in Phase 0 — one file, or the linked folder if it was split (config/code additionally into real source files where the user wants it):

1. **Dependency policy matrix** — one profile per dependency (Phase 2 format)
2. **Timeout budget tree** — end-to-end decomposition from the service's SLO down each call chain
3. **Resilience config** — in the user's library/mesh (Resilience4j/Polly/Envoy/…), composition order stated
4. **Fallback specifications** — per degradable dependency: mechanism, staleness contract, degraded-response signal
5. **Load-shedding design** — admission signal, priority classes, shed response (if in scope)
6. **Failure-mode walkthroughs** — the four scenarios per dependency
7. **Observability config** — metrics, alerts, trace attributes from 3.9
8. **Fault-injection test suite** — per-dependency scenarios in the user's test stack
9. **Gap list** — dependencies whose retries are blocked on missing idempotency, reclassification opportunities (critical → degradable/async), and timeout-chain violations found in the existing code
