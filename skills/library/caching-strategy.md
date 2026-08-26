---
name: caching-strategy
description: "Design caching architectures that are fast AND correct - cache placement (in-process, distributed, CDN), pattern selection (cache-aside, read-through, write-through, write-behind), TTL and invalidation strategy, stampede protection, and consistency guarantees. Use when database load is too high, latency needs cutting, the same data is fetched repeatedly, users see stale data after updates, cache and database disagree, a cache expiry causes load spikes (thundering herd), or the user asks where..."
version: 1.0.0
author: claude-skills-community (curated for Aion Hand)
license: MIT
metadata:
  tags: [backend, performance, platform]
  curated: true
  source: claude-skills-audit-2026-08
---
# Caching Strategy Architect

You are a senior systems engineer specializing in caching. Your job is to design a caching architecture that actually reduces load and latency without introducing the classic cache pathologies: stale data users notice, cache/DB inconsistency, stampedes on expiry, and memory blowups.

The discipline to enforce: **every cached item must declare who invalidates it, when, and how stale it may legally be.** A cache without an invalidation story is a data-corruption bug on a timer.

## When To Use

Trigger this skill when you observe these symptoms:

- Database CPU/IOPS driven by repeated identical reads; the same hot rows fetched on every request
- Latency targets missed on read-heavy endpoints that render slowly-changing data
- Users report seeing old data after they've updated something (stale-after-write)
- Cache and database disagree, and nobody can say which is right
- A cache flush, deploy, or hot-key expiry causes a load spike that takes the DB down (stampede/thundering herd)
- Redis/Memcached memory grows without bound, or eviction is churning constantly
- The user asks "should we cache this?", "where should the cache live?", or "how do we invalidate?"

Do NOT use this skill for: HTTP asset caching / CDN configuration for static files (covered adequately by cold-start-optimizer), database-internal tuning (buffer pools, query plans), or frontend state management stores.

---

## Phase 0: Output Format (ask first)

Before or together with context gathering, ask the user one question: should the final design document be **HTML** (default) or **Markdown**?

- **HTML (default)** — produce a single self-contained `.html` file: inline CSS only (no external assets, CDN links, or `<script>` tags), a linked table of contents, styled tables (data-class matrix, pattern comparison), `<pre><code>` blocks for code/config, diagrams as inline SVG (see below), readable typography, and a generation date in the footer. It must render well when opened directly in a browser.
- **Markdown** — produce a single `.md` file with the same structure; diagrams go in ```` ```mermaid ```` fenced blocks (rendered natively by GitHub, GitLab, VS Code, and Obsidian).

**Diagrams (both formats):** author every diagram (layer topology, race sequences) in Mermaid as the source of truth. Markdown output embeds the Mermaid block directly. HTML output must stay script-free, so hand-draw each diagram as inline SVG (responsive `viewBox` with `width:100%`, ~13-14px sans-serif labels, colors consistent with the document CSS) and keep the Mermaid source in an HTML comment beside the SVG so it remains regenerable. Never emit ASCII-art diagrams. Diagrams are a judgment call, not a quota: the ones named in this skill mark where structure usually outgrows prose — include them when the design has enough moving parts for a picture to pay off, and skip any diagram that would merely restate a small table or a sentence.

If the user doesn't state a preference or says "default", use HTML. Write the deliverable to a file (suggest `docs/caching-strategy.html` or `.md` in the current project; confirm or use the user's preferred path), then give a short summary of the key decisions in the chat reply. Implementation code additionally goes into real source files where the user wants it — the document embeds copies for reading.

**A single self-contained file is the default; when it would be too big, split the deliverable into a linked folder instead.** Use the folder form when the finished document would run past roughly 1,500 lines (~100 KB), when it has more than about six top-level sections a reader would navigate between, or whenever the user asks for it. Below that, keep the single file — a short design scattered across eight pages is worse than one page.

```
docs/caching-strategy/
  index.html                     overview, full contents, where each deliverable lives
  01-data-classes.html
  02-placement-and-patterns.html
  03-keys-and-ttls.html
  04-invalidation-and-races.html
  05-failure-and-security.html
  06-monitoring-and-rollout.html
  assets/styles.css              one shared stylesheet (still no CDN, no JS, no webfonts)
```

- **Split on top-level section boundaries only** — never mid-section, and never separate a table, diagram, or code block from the prose explaining it. Aim for 4-8 content files: merge anything that would come out shorter than a screenful, split further anything that would still be enormous alone.
- **Every page carries the same navigation**: the section list at the top (current page as plain text, not a link), previous/next links at the bottom, and a link home to `index.html`. `index.html` is the entry point — scope of the design, the full table of contents with a one-line summary per section, and a pointer to which file holds each Final Deliverable.
- **Relative links only** (`04-invalidation-and-races.html#write-race`), so the folder works opened from disk, moved, zipped, or committed. Every link must resolve to a file you actually wrote and an anchor that exists — verify them before delivering; a dead nav link is a failed deliverable.
- **Keep the pages one document**: the folder (not each page) is now the self-contained unit — shared stylesheet inside it, nothing fetched from the network, identical header and footer, the same generation date on every page, section numbering matching the index.
- **Markdown splits the same way**: `README.md` as the index plus `01-*.md` files, the same top nav line and previous/next footer, relative links, Mermaid blocks unchanged.

The folder is the deliverable — give its path in the chat reply and list the files with a phrase each.

---

## Phase 1: Context Gathering (Mandatory)

Before designing anything, determine the following. If working inside a codebase, inspect it first (existing cache clients, repository/DAO layers, hot queries, Redis config) and only ask what the code cannot answer:

1. **What data, what access pattern?** — Which entities/queries are candidates? For each: read:write ratio, request rate, size per item, cardinality (how many distinct keys), hot-key skew (do a few keys get most traffic?).
2. **Staleness tolerance per data class** — For each candidate: how stale may it be before it's a bug? (Prices vs. avatars vs. permission checks have wildly different answers.) Who is harmed by staleness — the same user who wrote, or others?
3. **Tech stack and infra** — Language/framework, existing cache infra (Redis/Memcached/Hazelcast), single instance or fleet, ORM in play (its cache layers matter).
4. **Write paths** — Who mutates the cached data? Only this service, multiple services, background jobs, or external systems/DBAs writing directly to the DB?
5. **Current pain** — Reduce DB load, cut latency, cut cost, or fix an existing broken cache? What are the current numbers (DB CPU, p99, hit ratio if a cache exists)?
6. **Consistency requirements** — Must a user read their own write immediately? Are there compliance/PII constraints on cached copies?

Do not proceed until you have answers to at least items 1-3.

**Partial context protocol:** If the user cannot answer questions 1-2 (critical), ask once more with concrete examples ("can a product page show a 60-second-old price?"). If still unknown, produce a design template with the data-class matrix left as fill-in rows, and state that TTLs without staleness requirements are guesses. For questions 3-6, proceed with stated assumptions. Never ask the same question more than twice.

**Scope gate:** If the request is "why is my existing cache wrong/slow" rather than new design, run the anti-pattern table (Phase 5) and consistency section (3.5) against the existing implementation first and lead with findings.

---

## Phase 2: Reference Example

Expected depth for every data class you design for.

### Data-Class Entry

| Field | Value |
|---|---|
| Data class | Product detail (id → name, price, stock flag) |
| Read:write | ~2000:1, 500 req/s peak, ~2KB/item, 1M items, top 1% of keys = 40% of traffic |
| Staleness budget | Price: 60s max (business-approved). Stock flag: 10s. Name/description: hours. → cache the tuple at the strictest budget: **10s TTL + event invalidation** |
| Placement | L1 in-process (Caffeine, 5s TTL, 10k entries) + L2 Redis (10s TTL + invalidation) |
| Pattern | Cache-aside with single-flight |
| Key | `prod:v2:{productId}` (v2 = schema version of the cached shape) |
| Invalidation | `ProductUpdated` event → DEL in Redis + pub/sub broadcast to clear L1s; TTL as backstop |
| Stampede guard | Per-key single-flight + jittered TTL (10s ± 20%) |
| Failure mode | Redis down → serve from L1 if present, else direct DB read through a concurrency-capped path (bulkhead), never error |

### Cache-aside with single-flight (pseudocode)

```
function getProduct(id):
    key = "prod:v2:" + id
    if (v = l1.get(key)) != null: return v
    if (v = redis.get(key)) != null:
        if v == TOMBSTONE: return null            // negative-cache hit — never return the sentinel as data
        l1.put(key, v); return v

    // Single-flight: only ONE loader per key per process; others wait on the same future.
    return singleflight(key, () -> {
        v = db.loadProduct(id)                    // the expensive call we're protecting
        if v == null:
            redis.set(key, TOMBSTONE, ttl=30s)    // negative cache: missing items get hammered too
            return null
        ttl = 10s * random(0.8, 1.2)              // jitter: no synchronized expiry
        redis.set(key, serialize(v), ttl)
        l1.put(key, v)
        return v
    })

function onProductUpdated(event):                 // consumer of the ProductUpdated event
    redis.del("prod:v2:" + event.productId)       // DELETE, do not SET the new value (see 3.5)
    pubsub.publish("l1-invalidate", "prod:v2:" + event.productId)
```

**Why DEL and not SET on update:** writing the new value into the cache from the update path races with concurrent cache-aside loaders — a loader that read the DB *before* your write can fill the cache *after* your SET, leaving the old value cached until TTL. Deleting forces the next reader to load fresh. (If update-in-place is required for hot keys, it needs a version/CAS check — design it explicitly or don't do it.) Show the race as a sequence diagram wherever the design must justify DEL-over-SET to reviewers:

```mermaid
sequenceDiagram
    participant Loader as Reader (cache-aside loader)
    participant Writer
    participant Cache
    participant DB
    Loader->>DB: read product (price = 10)
    Writer->>DB: UPDATE price = 12, COMMIT
    Writer->>Cache: SET price = 12
    Loader->>Cache: fill price = 10
    Note over Cache: stale value 10 wins — cached until TTL.<br/>With DEL instead of SET, the next reader reloads 12.
```

---

## Phase 3: Design Output Structure

### 3.1 Cache Placement (layers)

Decide per data class; justify against latency, consistency, and fleet size:

- **L1 in-process** (Caffeine, cachetools `TTLCache`, a TTL-wrapped map): ~100ns, free of network hops; but per-instance (N copies, N inconsistencies) and invalidation requires broadcast. Small TTLs (seconds), bounded size (entries + weigher), only for hot, small, staleness-tolerant items.
- **L2 distributed** (Redis/Memcached): ~1ms, shared truth for the fleet, supports targeted invalidation, atomic ops. The default layer for most classes.
- **L1 + L2**: for hot-key skew (protects Redis itself from hot-key saturation). Rule: L1 TTL ≤ ½ of L2 TTL, and L1 must subscribe to invalidation broadcasts.
- **HTTP layer** (CDN/gateway with `Cache-Control`/`ETag`/`Vary`): for anonymous, shared responses only. Never cache per-user responses at a shared HTTP layer without an exact `Vary` contract — this is how session-leak incidents happen.
- **Materialized views / replica reads**: when the "cache" is really a precomputed query, prefer DB-native materialization over hand-rolled cache maintenance.

When the design has more than one layer or any invalidation path beyond TTL, close this section with one layer topology diagram (Mermaid `flowchart LR`): the read path through every chosen layer with its TTL, and every invalidation path (write event → DEL in L2 → pub/sub broadcast to L1s), e.g.:

```mermaid
flowchart LR
    R[request] --> L1["L1 in-process (Caffeine, 5s TTL)"]
    L1 -->|miss| L2[("L2 Redis (10s TTL ± 20%)")]
    L2 -->|miss, single-flight| DB[(PostgreSQL)]
    EV[ProductUpdated event] -->|DEL| L2
    EV -->|pub/sub broadcast| L1
```

### 3.2 Pattern Selection

| Pattern | Write path | Read path | Consistency | Use when |
|---|---|---|---|---|
| **Cache-aside** (default) | App writes DB, then DELs cache | Miss → load DB → fill | Stale ≤ TTL after races; simple to reason about | General case; multiple writers to DB exist |
| **Read-through** | Same as aside | Cache library owns loading | Same as aside, less app code | The cache client/library supports loaders well |
| **Write-through** | App writes cache, cache writes DB synchronously | Always warm | Strong-ish for single writer; write latency up | Read-heavy data that must be warm immediately after write |
| **Write-behind** | App writes cache; async flush to DB | Always warm | **DB lags cache; data loss on cache crash** | Almost never for source-of-truth data; counters/analytics only, with durability accepted |
| **Refresh-ahead** | — | Background refresh before expiry for hot keys | Hides reload latency | Predictably hot keys with expensive loads |

State explicitly: the **database remains the source of truth** in every pattern except deliberately-accepted write-behind cases. Any design where "the cache has data the DB doesn't yet" must name the durability story or be rejected.

### 3.3 Key Design and TTL Strategy

- **Key schema**: `{domain}:{schema-version}:{id}` — the embedded version makes deploy-time shape changes safe (new code reads new keys; old entries die by TTL; no flush needed).
- **Cardinality bound**: state the max distinct keys and size per entry → projected memory. Unbounded key spaces (per-query-string keys, unhashed user input in keys) are rejected at design time.
- **TTL per data class**, derived from the staleness budget from Phase 1 — never one global TTL. **Jitter every TTL** (±10-20%) to prevent synchronized expiry of items cached together (deploy warm-ups, bulk imports).
- **Negative caching**: cache misses/404s with a short TTL — missing keys get hammered hardest (misspelled IDs, deleted items, scrapers). Distinct tombstone value, never confusable with real data.
- **Eviction policy**: size-bound every cache (`maxmemory` + `allkeys-lru`/`allkeys-lfu` in Redis; entry/weight bounds in-process). LFU when hot-key skew is strong, LRU otherwise. A cache relying on TTL alone for memory control will OOM on cardinality growth.

### 3.4 Invalidation Design

For every data class, answer: **what events make this entry wrong, and what do we do about each?**

- **TTL-only**: acceptable when the staleness budget is honestly ≥ the TTL. Cheapest; document it as a business-approved decision, not a shrug.
- **Explicit invalidation on write** (DEL, as in Phase 2): required when staleness budget < practical TTL. Enumerate ALL write paths — the update endpoint everyone remembers, plus admin tools, batch jobs, and other services. A single unenumerated write path is a permanent stale-data bug.
- **Event-driven invalidation**: when writers are other services, subscribe to their domain events (see event-pipeline-architect) and invalidate on consume. Note the propagation delay as part of the staleness budget.
- **External writers** (DBA scripts, legacy apps writing straight to the DB): if they exist and can't emit events, either CDC (Debezium → invalidation consumer) or an honest "TTL is the only guarantee" with the TTL sized accordingly.
- **Versioned-key invalidation** for collections: bump a namespace version (`search:v{n}:...`) instead of enumerating and deleting thousands of entries.
- **Broadcast for L1s**: pub/sub invalidation channel; L1 entries must also carry their own short TTL as the backstop for lost messages (pub/sub is fire-and-forget).

### 3.5 Consistency and Races

Address each explicitly — these are the bugs that make teams distrust their cache:

- **Write-then-fill race**: covered by DEL-not-SET (Phase 2). If using SET, require a version check.
- **DB-write / cache-DEL ordering**: DEL after commit. DEL-before-write leaves a window where a reader refills the old value. If the DEL can fail independently of the commit, either retry it via outbox-style follow-up or accept TTL as the bound — state which.
- **Read-your-own-writes**: if required, choose one: (a) DEL + read-through is usually sufficient (next read loads fresh); (b) session-pinned bypass (after a write, that session reads the DB for N seconds); (c) write-through for that class. Name the choice per class where it matters (profile edits: yes; view counters: no).
- **Two caches disagreeing (L1 vs L2)**: bounded by L1 TTL + broadcast; state the worst-case window and check it against the staleness budget.
- **Do not cache uncommitted data**: fills happen from committed reads only; never populate a cache inside a transaction that may roll back.

### 3.6 Stampede and Hot-Key Protection

- **Single-flight per key** (per process) so a miss triggers one load, not one per concurrent request. For fleet-wide protection on very expensive loads: a short Redis lock (`SET NX PX`) where lock losers serve stale-if-available or wait briefly.
- **Stale-while-revalidate**: serve the expired value while one loader refreshes — best UX for tolerant data; store `(value, soft_ttl, hard_ttl)`.
- **Probabilistic early refresh** for hot keys: refresh slightly before expiry with probability increasing toward expiry (avoids the cliff entirely).
- **Cold-start protection**: after deploy/flush, the cache is empty at full traffic. Either warm critical keys before taking traffic, or cap concurrent DB loads (bulkhead) and accept elevated latency — plan it, don't discover it.

### 3.7 Failure Modes and Security

- **Cache down ≠ outage**: reads fall through to the DB behind a concurrency cap (the DB was sized assuming the cache — uncapped fallthrough is the stampede again). Define: does the app degrade (slower) or shed (reject low-priority reads)? Wire the cache client with short timeouts (a slow cache is worse than no cache — the resilience-strategist rules apply to the cache itself).
- **PII in caches**: cached copies are copies — they inherit GDPR/erasure obligations. Deletion flows must purge caches; either include caches in the erasure path or keep PII TTLs short enough to cite as the erasure bound. Encrypt at rest where the store supports it and compliance requires.
- **Authorization**: cache data, not authorization decisions — or key the entry by the permission context. A cached response that ignores the viewer's permissions is a data leak (the shared-HTTP-layer variant of this took down real companies).

### 3.8 Monitoring

Metrics with names and alert intents:
- `cache.hit_ratio{class, layer}` — the headline number; alert on drops (invalidation bug, key churn, or traffic shift). Target set per class in the design (e.g., >90% for product reads), not a universal number.
- `cache.load_duration{class}` + `cache.loads{class}` — what the DB actually absorbs; this times the stampede guards' effectiveness
- `cache.evictions{layer}` (churn = undersized or unbounded keys) · `cache.memory_used` vs limit
- `cache.stale_served{class}` (stale-while-revalidate is active — fine, but watch it) · `cache.invalidations{class}` (zero invalidations on a class with write-invalidation = a broken pipeline)
- `cache.fallthrough_concurrent` (gauge vs the bulkhead cap — how close cache-down is to hurting)

### 3.9 Rollout and Testing

- Roll out per data class: shadow-read first if correctness is critical (read both cache and DB, compare, log divergence, serve DB), then serve-from-cache.
- **Test scenarios** (specify per class): stale-after-write (write, read within/after budget), invalidation race (concurrent write + read at the boundary), stampede simulation (expire hot key under concurrent load, assert single DB load), cache-down fallthrough under load (assert the cap holds), L1 broadcast loss (assert TTL backstop bounds staleness), negative-cache correctness (item created after tombstone must appear within tombstone TTL).
- Every cache added must cite its **before/after target** (DB load, p99) and the rollout must measure it — a cache that doesn't move the target number is complexity to be removed.

---

## Anti-Patterns (Avoid These)

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Caching without a staleness budget | "How stale is too stale" gets answered by an incident | Budget per data class, business-approved, drives TTL |
| SET-on-update from the write path | Races with in-flight loaders; old value cached until TTL | DEL on write; loaders refill (or CAS-versioned SET) |
| One global TTL for everything | Either prices are too stale or avatars are reloaded pointlessly | TTL per data class from its budget |
| No TTL jitter | Items cached together expire together → periodic load spikes | ±10-20% jitter everywhere |
| Unbounded keys (raw query strings, user input in keys) | Memory blowup, eviction churn, cache-poisoning surface | Bounded, normalized, versioned key schema |
| Cache as source of truth (accidental write-behind) | Cache crash = data loss | DB is truth; write-behind only by explicit durability decision |
| Caching inside an open transaction | Rollback leaves phantom data cached | Fill from committed reads only |
| No plan for cache-down | "Redis restarted" becomes a DB stampede outage | Capped fallthrough + degraded mode, tested under load |
| Ignoring negative lookups | Deleted/missing IDs bypass the cache and hammer the DB | Short-TTL tombstones |
| Per-user data under shared HTTP cache keys | One user's response served to another | `Vary` contract or don't cache at the shared layer |
| Caching permission-dependent data without the permission in the key | Privilege changes don't propagate; data leaks | Key by viewer context or don't cache the decision |
| Invalidation only on the "main" write path | Admin tools/batch jobs create permanent stale entries | Enumerate every write path; CDC for external writers |
| Adding a cache before measuring the query | Complexity without benefit; sometimes an index was the fix | Baseline first; state the target number the cache must move |

---

## Testable Constraints

Every design you produce must satisfy these. Verify each before delivering:

1. Every data class has: staleness budget (with who approved it), placement, pattern, key schema, TTL + jitter, invalidation trigger list, stampede guard, and failure mode.
2. Every invalidation-on-write class enumerates ALL write paths, including admin/batch/external; external writers have CDC or an explicit TTL-only acknowledgment.
3. The write path uses DEL (or version-checked SET) — no naive SET-on-update.
4. All caches are size-bounded with a stated eviction policy; projected memory is computed from cardinality × entry size.
5. Hot classes have single-flight or equivalent; the cold-start/flush scenario has a plan.
6. Cache-down behavior is defined with a concurrency cap on fallthrough, and the cache client has explicit short timeouts.
7. Read-your-own-writes is explicitly decided per class where users edit data.
8. PII classes have an erasure story.
9. Each cache states the metric it must improve and the target; test scenarios from 3.9 are included per class.

---

## Final Deliverables

Hand back exactly these artifacts, compiled into the HTML or Markdown deliverable chosen in Phase 0 — one file, or the linked folder if it was split (code additionally into real source files where the user wants it):

1. **Data-class matrix** — one entry per class in the Phase 2 format
2. **Placement & pattern decisions** — layers and pattern per class with tradeoffs stated, plus the layer topology diagram (read path + every invalidation path)
3. **Key schema & TTL table** — schema, versioning, TTLs with jitter, negative-cache policy, memory projection
4. **Invalidation design** — trigger list per class, event/CDC wiring, L1 broadcast design
5. **Consistency notes** — race handling and read-your-own-writes decision per class
6. **Implementation code** — cache access layer with single-flight, invalidation consumer, config, in the user's stack
7. **Failure-mode plan** — cache-down degraded path, cold-start plan, capped fallthrough
8. **Monitoring config** — metrics, per-class hit-ratio targets, alerts
9. **Rollout & test plan** — per-class rollout order, shadow-read where needed, the 3.9 test scenarios, before/after targets
