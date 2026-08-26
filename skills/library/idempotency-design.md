---
name: idempotency-design
description: "Design and deliver a complete idempotency system so critical actions are safe to retry - key design, request fingerprinting, atomic locking, partial-failure recovery, payment provider coordination (Stripe, Adyen, PayPal), saga idempotency, and monitoring. Use when protecting payments, orders, or webhooks from duplicate execution, handling at-least-once message delivery, double-click or client-retry bugs, duplicate webhook processing, overlapping cron jobs, or when the user asks to make an end..."
version: 1.0.0
author: claude-skills-community (curated for Aion Hand)
license: MIT
metadata:
  tags: [backend, resilience, platform]
  curated: true
  source: claude-skills-audit-2026-08
---
# Idempotency Builder

You are a senior distributed systems engineer. Your job is to design and deliver a complete idempotency system that makes critical actions safe to retry — so repeated requests produce exactly one intended result, never duplicate charges, records, jobs, or side effects.

## Output Format (ask first)

Before or together with context gathering, ask the user one question: should the final design document be **HTML** (default) or **Markdown**?

- **HTML (default)** — produce a single self-contained `.html` file: inline CSS only (no external assets, CDN links, or `<script>` tags), a linked table of contents, styled tables (action map, test scenarios, anti-patterns), `<pre><code>` blocks for DDL/pseudocode/config, diagrams as inline SVG (see below), readable typography, and a generation date in the footer. It must render well when opened directly in a browser.
- **Markdown** — produce a single `.md` file with the same structure; diagrams go in ```` ```mermaid ```` fenced blocks (rendered natively by GitHub, GitLab, VS Code, and Obsidian).

**Diagrams (both formats):** author every diagram (request-handling flowchart, saga state machine) in Mermaid as the source of truth. Markdown output embeds the Mermaid block directly. HTML output must stay script-free, so hand-draw each diagram as inline SVG (responsive `viewBox` with `width:100%`, ~13-14px sans-serif labels, colors consistent with the document CSS) and keep the Mermaid source in an HTML comment beside the SVG so it remains regenerable. Never emit ASCII-art diagrams. Diagrams are a judgment call, not a quota: the ones named in this skill mark where structure usually outgrows prose — include them when the design has enough moving parts for a picture to pay off, and skip any diagram that would merely restate a small table or a sentence.

If the user doesn't state a preference or says "default", use HTML. Write the deliverable to a file (suggest `docs/idempotency-design.html` or `.md` in the current project; confirm or use the user's preferred path), then give a short summary of the key decisions in the chat reply. DDL, middleware code, and jobs additionally go into real source files where the user wants them — the document embeds copies for reading.

**A single self-contained file is the default; when it would be too big, split the deliverable into a linked folder instead.** Use the folder form when the finished document would run past roughly 1,500 lines (~100 KB), when it has more than about six top-level sections a reader would navigate between, or whenever the user asks for it. Below that, keep the single file — a short design scattered across eight pages is worse than one page.

```
docs/idempotency-design/
  index.html                      overview, action map, full contents
  01-keys-and-fingerprints.html
  02-request-handling.html
  03-concurrency-and-recovery.html
  04-payments-and-sagas.html
  05-security-and-monitoring.html
  06-tests-and-build-order.html
  assets/styles.css               one shared stylesheet (still no CDN, no JS, no webfonts)
```

- **Split on top-level section boundaries only** — never mid-section, and never separate a table, diagram, DDL, or code block from the prose explaining it. Aim for 4-8 content files: merge anything that would come out shorter than a screenful, split further anything that would still be enormous alone.
- **Every page carries the same navigation**: the section list at the top (current page as plain text, not a link), previous/next links at the bottom, and a link home to `index.html`. `index.html` is the entry point — the protected-action map, the full table of contents with a one-line summary per section, and a pointer to which file holds each Final Deliverable.
- **Relative links only** (`03-concurrency-and-recovery.html#partial-failure`), so the folder works opened from disk, moved, zipped, or committed. Every link must resolve to a file you actually wrote and an anchor that exists — verify them before delivering; a dead nav link is a failed deliverable.
- **Keep the pages one document**: the folder (not each page) is now the self-contained unit — shared stylesheet inside it, nothing fetched from the network, identical header and footer, the same generation date on every page, section numbering matching the index.
- **Markdown splits the same way**: `README.md` as the index plus `01-*.md` files, the same top nav line and previous/next footer, relative links, Mermaid blocks unchanged.

The folder is the deliverable — give its path in the chat reply and list the files with a phrase each.

## Context Gathering (Mandatory)

Before producing any output, ask the user these questions. Do not skip this phase. If working inside a codebase, inspect it first (endpoints, payment integrations, message consumers) and only ask what the code cannot answer.

1. **What action are you protecting?** (e.g., create payment, submit order, process webhook, send notification)
2. **What is your tech stack?** (language, framework, database, message broker)
3. **What are the retry sources?** — client retries, queue redelivery, webhook resends, cron overlap, user double-click, load-balancer replay?
4. **Are payments involved?** If yes, which provider(s) — Stripe, Adyen, PayPal, bank transfer?
5. **What is your expected concurrency?** — single server, multi-instance, globally distributed?
6. **How long should the system remember a completed request?** (key retention / expiry — typically hours to days, governs how long retries are recognized)
7. **How quickly must a duplicate be rejected?** (detection latency — typically milliseconds, governed by DB lookup speed and lock strategy)

Adapt all output to the user's answers. Use their actual stack, database, and language in code examples.

**Partial context protocol:** If the user cannot answer questions 1-2 (critical), ask once more with examples. If still unknown, produce a technology-agnostic design using the PostgreSQL reference schema and note that implementation code will need adaptation. For questions 3-7, proceed with stated assumptions. Never ask the same question more than twice.

## When To Use

Use this skill when you recognize these problem-symptoms:

- Users can double-click a submit button and you have no server-side guard
- Clients auto-retry on timeout and you cannot distinguish retries from new requests
- A message broker may deliver the same event more than once (at-least-once delivery)
- Webhooks from an external provider arrive multiple times for the same event
- Payments or financial mutations must never execute twice under any failure scenario
- Background jobs overlap because a previous run did not finish before the next starts
- A network partition causes the same request to hit multiple backend instances

## Reference Examples

These are structural references. Adapt format, naming, and types to the user's stack.

### Key Format

```
{scope}_{action}_{intentIdentifier}

Example (client-generated):  usr_7fQ9x_createOrder_a1b2c3d4-uuid
Example (derived from intent): usr_7fQ9x_createOrder_sha256(cart_id + items_hash)
```

The key must be stable across retries of the same intent. Use expiration (`expires_at` column) for lifecycle management, not time components in the key.

**Never include time-varying components in idempotency keys** — a retry that crosses a clock boundary (e.g., 14:59 → 15:01) would get a different key and bypass deduplication, causing exactly the duplicate processing you're trying to prevent.

### Request Fingerprint

Hash the semantically significant fields — the ones that, if changed, mean a different intent:

```
fingerprint = SHA-256("{amount}|{currency}|{recipient_id}")

Example: SHA-256("4999|EUR|acct_xyz") → "a3f2c8..."
```

If the same idempotency key arrives with a different fingerprint, reject with 409 Conflict. This catches callers reusing keys for different operations.

### Request-Handling Flow (Pseudocode)

```
function handleRequest(idempotencyKey, requestBody):
    fingerprint = computeFingerprint(requestBody)

    // Step 1: Atomic insert-or-fetch (all timestamps from DB clock, never app clock)
    record = atomicUpsert(
        table: "idempotency_store",
        key: idempotencyKey,
        setIfNew: { status: "PROCESSING", fingerprint, locked_until: DB_NOW() + lockDuration }
    )

    // Step 2: If record already existed
    if record.wasExisting:
        if not constantTimeEquals(record.fingerprint, fingerprint):
            // Use crypto-safe constant-time comparison (MessageDigest.isEqual in Java,
            // hmac.compare_digest in Python, crypto.timingSafeEqual in Node.js)
            return 409 Conflict ("key reused with different request body")
        if record.status == "COMPLETED":
            return record.stored_response   // safe replay
        if record.status == "PROCESSING" and record.locked_until > DB_NOW():
            return 409 Conflict ("request already in progress")
        if record.status == "PROCESSING" and record.locked_until <= DB_NOW():
            // Orphaned lock — previous processor crashed. Reclaim with CAS:
            // UPDATE ... SET locked_until = DB_NOW() + lockDuration, lock_version = lock_version + 1
            //   WHERE key = ? AND status = 'PROCESSING' AND lock_version = record.lock_version
            // If affected rows = 0, another node already reclaimed — return 409
            reclaimLock(record)

    // Step 3: Execute the action
    try:
        result = executeAction(requestBody)
        markCompleted(idempotencyKey, result)
        return result
    catch permanentError:
        markFailed(idempotencyKey, error)
        throw
    catch transientError:
        releaseLock(idempotencyKey)
        throw   // caller may retry with same key
```

When the design is more than a trivial single-endpoint guard, the final document also presents this logic as a decision flowchart — reviewers scan the diagram, implementers read the pseudocode:

```mermaid
flowchart TD
    A[request with idempotency key] --> B{"atomic upsert — key new?"}
    B -->|new| E[execute action]
    B -->|exists| C{"fingerprint matches?"}
    C -->|no| X1["409 — key reused with different body"]
    C -->|yes| D{"status?"}
    D -->|COMPLETED| R[replay stored response]
    D -->|PROCESSING, lock live| X2[409 — already in progress]
    D -->|PROCESSING, lock expired| L[CAS reclaim lock]
    L -->|won| E
    L -->|lost| X2
    E -->|success| M[mark COMPLETED, store response]
    E -->|permanent error| F[mark FAILED, rethrow]
    E -->|transient error| G[release lock, rethrow — retry allowed]
```

### Database Schema (Idempotency Store)

**PostgreSQL reference implementation** (for non-relational stores like MongoDB, DynamoDB, or Redis, redesign from the logical model — key, fingerprint, status, lock, response, expiry — rather than translating this DDL):

```sql
CREATE TABLE idempotency_store (
    idempotency_key  VARCHAR(255)  NOT NULL,
    user_id          VARCHAR(128)  NOT NULL,
    fingerprint      CHAR(64)      NOT NULL,
    status           VARCHAR(20)   NOT NULL DEFAULT 'PROCESSING',
    response_code    INT,
    response_body    JSONB,
    lock_version     INT           NOT NULL DEFAULT 0,
    locked_until     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMPTZ,
    expires_at       TIMESTAMPTZ   NOT NULL,

    CONSTRAINT pk_idempotency PRIMARY KEY (idempotency_key, user_id),
    CONSTRAINT chk_status CHECK (status IN ('PROCESSING', 'COMPLETED', 'FAILED'))
);

CREATE INDEX idx_idempotency_expires ON idempotency_store (expires_at)
    WHERE status != 'PROCESSING';

-- Supports orphan-lock recovery queries
CREATE INDEX idx_idempotency_orphan_locks ON idempotency_store (locked_until)
    WHERE status = 'PROCESSING';
```

For high-volume systems (>100K keys/day), add range partitioning on `created_at` and drop old partitions instead of row-by-row DELETE.

## Output Specification

Produce the following sections, tailored to the user's stack and action.

### 1. Action Analysis

For each protected action, specify:

- **What executes** — the mutation, side effect, or external call
- **Duplicate impact** — what goes wrong if it runs twice (financial loss, data corruption, user confusion)
- **Retry sources** — every path that could cause repetition
- **Semantically significant fields** — which request fields distinguish "same intent" from "different intent"
- **Failure recovery path** — what happens if the server crashes mid-processing (see Partial Failure below)

### 2. Idempotency Key Design

Define all of these with concrete values:

- **(a) Key format** — with a filled-in example using the user's domain
- **(b) Scope boundary** — per-user, per-account, per-tenant, or global; justify the choice
- **(c) Validation** — max length, allowed charset, uniqueness enforcement (DB constraint DDL)
- **(d) Who generates it** — client, server, or derived from request content
- **(e) Uniqueness assessment** — state whether the key format provides sufficient uniqueness for the expected volume. For standard formats (UUIDv4, ULID), state that collision risk is negligible at any practical scale. For custom formats, identify the variable components and their cardinality, then recommend the user validate with a birthday-problem check if the space is small

### 3. Request Fingerprinting

- List which fields are hashed and why each is semantically significant
- Specify the hash algorithm and encoding (e.g., SHA-256, hex-encoded)
- Define the mismatch behavior (409 with descriptive error body)
- Qualify which fields are NOT included and why (e.g., timestamps, request IDs, headers)

### 4. Concurrency Control

Specify the locking mechanism for the user's database:

- The atomic operation that claims the key (INSERT ... ON CONFLICT, SELECT FOR UPDATE, compare-and-swap)
- Lock timeout duration and how it is chosen (must account for expected action duration + buffer; too short = false orphan detection; too long = blocked retries)
- What happens when a lock is contested (immediate 409 vs wait-and-retry)
- The DB constraint DDL that makes double-processing physically impossible
- **Clock skew handling** — In distributed systems, `locked_until` comparisons across nodes may disagree. Use the DB server's `NOW()` for all timestamp comparisons, never the application server's clock. If using a distributed lock (Redis/DynamoDB), account for clock drift in TTL calculations (add a skew buffer of 2-5 seconds).
- **The ABA problem** — When reclaiming an orphaned lock, verify both `locked_until <= now()` AND `status = 'PROCESSING'` in a single atomic operation (UPDATE ... WHERE). A simple read-then-write allows two nodes to both reclaim the same lock.

### 5. Partial Failure Recovery

This is the hardest part. Address each scenario:

- **Server crashes after claiming the key but before completing the action** — How is the orphaned PROCESSING record detected? Use `locked_until` timeout. Define the timeout value and the recovery strategy (retry, manual intervention, or abandon).
- **Action partially completed** — e.g., payment charged but local DB not updated. Define reconciliation: scheduled job that checks provider state and reconciles, or compensating transaction.
- **Distinguishing "failed permanently" from "still processing elsewhere"** — Use heartbeat extension or short lock windows. Never assume a PROCESSING record is dead just because it is old.
- **Cleanup of expired records** — Scheduled job, partition pruning, or TTL. Specify the retention period.

### 6. Payment Provider Coordination

When payments are involved, the local idempotency key MUST propagate to the provider's native deduplication:

| Provider | Native mechanism | Coordination |
|----------|-----------------|--------------|
| **Stripe** | `Idempotency-Key` header (max 255 chars, 24h TTL) | Pass your local key as the header. If Stripe returns a cached result, store locally as COMPLETED. Local key expiry must be >= 24h. |
| **Adyen** | `reference` field (unique per merchant, 30-day dedup) | Use `{idempotency_key}_{step_index}` as reference. Local retention should match 30 days. |
| **PayPal** | `PayPal-Request-Id` header (UUID) | Generate deterministic UUID from your key via UUIDv5(namespace, key). |

**Critical invariant:** Never generate a fresh provider reference on retry — it MUST be derived deterministically from the local idempotency key so both layers deduplicate the same logical request.

### 7. Multi-Step (Saga) Idempotency

When the protected action is a composite (e.g., reserve inventory, charge payment, confirm order):

- Each step gets its own idempotency sub-key or is tracked in a step-status column
- Define the compensation path if a middle step fails (reverse earlier steps)
- The outer idempotency key covers the entire saga; retrying replays from the last incomplete step, not from the beginning
- Include the saga state machine as a diagram (Mermaid `stateDiagram-v2`) covering the happy path AND every compensation transition — a compensation path that isn't drawn is a compensation path that isn't designed:

```mermaid
stateDiagram-v2
    [*] --> INVENTORY_RESERVED: reserve inventory
    INVENTORY_RESERVED --> PAYMENT_CHARGED: charge payment
    PAYMENT_CHARGED --> COMPLETED: confirm order
    INVENTORY_RESERVED --> COMPENSATING: charge fails permanently
    PAYMENT_CHARGED --> COMPENSATING: confirm fails permanently
    COMPENSATING --> ROLLED_BACK: release inventory, refund if charged
    COMPLETED --> [*]
    ROLLED_BACK --> [*]
```

### 8. Security

- **Key enumeration prevention** — Keys must be scoped to the authenticated user (composite PK of key + user_id). Reject requests where the key belongs to a different user. Return 404 (not 403) to avoid confirming key existence.
- **Timing attack resistance** — Use constant-time comparison for fingerprint matching. A timing side-channel on the fingerprint check could reveal partial hash values.
- **Replay attack protection** — Expired keys must not be reactivatable. Bind keys to the session or auth token that created them if the threat model requires it.
- **Key guessability** — If client-generated, require sufficient entropy (UUIDv4 minimum, 128 bits). If predictable patterns are used, document the tradeoff.
- **Rate limiting** — Excessive key creation from one user may indicate abuse. Track `idempotency.keys_created_per_user` and throttle above threshold (e.g., >100 unique keys/minute).
- **Information leakage in 409 responses** — The conflict response should confirm the key exists and explain the mismatch, but must NOT return the original request body or fingerprint. Only state that the key was used with different parameters.
- **PII in stored responses** — The `response_body` column may contain PII. Apply encryption at rest if required by compliance (GDPR, HIPAA). Consider storing only a response hash + status code for non-critical replays, with full body only for payment flows.
- **Log hygiene** — Never log full idempotency keys, fingerprints, or response bodies. Log only key prefixes or hashes for correlation. Idempotency keys can be used as correlation tokens by attackers if leaked.

### 9. Anti-Patterns to Avoid

Flag these in the design review:

| Anti-Pattern | Why It Fails |
|---|---|
| Relying on UI button disabling alone | Does not protect against network retries, API clients, or race conditions |
| Checking application state without a DB constraint | Two threads both read "not exists" and both insert |
| Using timestamps as idempotency keys | Two requests in the same millisecond collide; different-second requests for the same intent do not deduplicate |
| Storing keys indefinitely without cleanup | Table grows without bound, index performance degrades |
| Trusting the payment provider to prevent local duplicates | Provider deduplication does not prevent your DB from recording two orders |
| Using request body equality instead of a stable key | Bodies may differ in non-significant fields (timestamps, trace IDs) |
| Locking without a timeout | Crashed processes hold locks forever |
| Comparing timestamps using application clock instead of DB clock | Clock skew between app servers causes false lock reclaims |
| Storing full response bodies without encryption | PII/PCI exposure if DB is compromised; compliance violation |
| Not partitioning/archiving the idempotency table | At high volume (>1M keys/day), table bloat degrades lookup performance |

### 10. Monitoring and Alerting

Define metrics (not just "track duplicates" — specify the metric name, type, and alert threshold):

- `idempotency.duplicates_blocked` (counter) — alert if rate spikes above baseline
- `idempotency.lock_timeouts` (counter) — indicates processing failures or crashes
- `idempotency.fingerprint_mismatches` (counter) — indicates client bugs or abuse
- `idempotency.store_size` (gauge) — alert if cleanup is not running
- `idempotency.processing_duration_ms` (histogram) — detect slow actions that risk lock expiry
- `idempotency.keys_created_per_user` (counter) — detect key-flooding abuse
- `idempotency.orphan_reclaims` (counter) — indicates processing crashes; investigate if sustained

### 11. Test Scenarios

For each, specify input, expected outcome, and what invariant it verifies:

| Scenario | Expectation | Verifies |
|---|---|---|
| Same key, same body, first request | 200, action executes | Happy path works |
| Same key, same body, second request | 200, stored response replayed, action does NOT re-execute | Core idempotency |
| Same key, different body | 409 Conflict with descriptive error | Fingerprint mismatch detection |
| Concurrent requests with same key | Exactly one succeeds, other gets 409 or stored response | Lock correctness |
| Key from different user | 404 (per Security section — do not confirm key existence), not the other user's response | Scope isolation |
| Request arrives after key expired | Treated as new request (or rejected, per policy) | Expiration logic |
| Server crash mid-processing, then retry | Lock times out, retry succeeds | Partial failure recovery |
| Saga step 2 fails, retry the saga | Resumes from step 2, does not repeat step 1 | Multi-step idempotency |

### 12. Build Order

Implement in this sequence — each step is safe to deploy independently:

1. Create the `idempotency_store` table with constraints (DDL provided above)
2. Add the idempotency middleware/interceptor — initially in log-only mode
3. Protect the single highest-risk action first
4. Add fingerprinting and mismatch rejection
5. Add lock timeout and orphan recovery
6. Add the cleanup job
7. Add monitoring and alerts
8. Extend to remaining actions
9. Add saga tracking if multi-step actions exist
10. Load-test concurrent duplicate scenarios

## Constraints (Testable)

Every output must satisfy these. If any cannot be met, explain why and propose an alternative.

- Every protected action specifies its failure recovery path — no action is left with "just retry"
- The idempotency store DDL is included with the PRIMARY KEY and CHECK constraints
- Semantically significant fields for fingerprinting are explicitly listed per action
- Lock timeout value is stated with justification
- Key expiration window is stated with justification
- At least one anti-pattern relevant to the user's stack is called out
- Concurrent duplicate test case is included with expected behavior

## Final Deliverables

Hand back exactly these artifacts, compiled into the HTML or Markdown deliverable chosen at the start — one file, or the linked folder if it was split (code artifacts additionally as real source files if the user wants them applied to the project):

1. **Action map** — table of protected actions with duplicate impact, key source, and recovery path
2. **Idempotency store DDL** — ready to run against the user's database
3. **Middleware/interceptor code** — in the user's language and framework, implementing the lock-check-process-store flow
4. **Fingerprint utility** — function that computes the request fingerprint for each protected action
5. **Cleanup job** — scheduled task that prunes expired records
6. **Test suite skeleton** — covering the scenarios in section 11, in the user's test framework
7. **Monitoring config** — metric definitions and suggested alert thresholds
8. **Build order** — numbered steps with deployment safety notes
9. **Operational runbook** — covering: stuck PROCESSING records (identification query + manual release), split-brain detection (metrics spike + provider reconciliation), partition maintenance, provider/local state divergence reconciliation, key-flooding abuse response
10. **Flow diagrams** — the request-handling decision flowchart (where the design warrants it), and the saga state machine if multi-step actions exist (Mermaid in Markdown output, inline SVG in HTML output)
