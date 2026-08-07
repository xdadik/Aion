---
name: performance-optimization
description: "Measure → Profile → Optimize → Verify. Never optimize without a benchmark; never guess the bottleneck."
version: 1.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [performance, optimization, profiling]
---

# Performance Optimization

Use this skill when making code faster.

## The Golden Rule

> Premature optimization is the root of all evil. — Knuth

**Don't optimize unless you have a measured problem.**

## The Method

### 1. Measure
- Establish a baseline: `time`, `%timeit`, `pytest-benchmark`, `ab`, `wrk`
- Define what "fast enough" looks like — stop when you hit it
- Measure realistic workloads, not synthetic

### 2. Profile
- Python: `cProfile`, `py-spy`, `line_profiler`
- Memory: `memory_profiler`, `tracemalloc`
- I/O: `strace`, `iotop`
- DB: `EXPLAIN ANALYZE`, slow query log

**Identify the bottleneck:**
- CPU-bound? → algorithm, cache, parallelism
- I/O-bound? → async, batching, caching
- Memory-bound? → streaming, smaller structures
- Network-bound? → CDN, compression, fewer round trips

### 3. Optimize
- **Algorithm first.** O(n) → O(log n) beats any micro-optimization.
- **Cache next.** Memoize, HTTP cache, DB cache.
- **Batch I/O.** 1 query fetching 100 rows > 100 queries fetching 1 row.
- **Parallelize.** Async for I/O, multiprocessing for CPU.
- **Cython/C extensions.** Last resort, only for hot inner loops.

### 4. Verify
- Re-run the benchmark. Did it actually get faster?
- Run the test suite. Did you break anything?
- Measure the new baseline. Save it.

### 5. Document
- Commit message: "perf: 4x faster search via inverted index (was 800ms, now 200ms)"
- Note the tradeoffs (memory? complexity?)

## Common Patterns

### N+1 Query
```python
# Bad — 1 + N queries
for user in User.objects.all():
    print(user.profile.bio)  # 1 query per user

# Good — 1 query with join
for user in User.objects.select_related('profile').all():
    print(user.profile.bio)
```

### Loop Invariant Hoisting
```python
# Bad — recomputes len(data) every iteration
for i in range(len(data)):
    process(data[i], len(data))

# Good — compute once
n = len(data)
for i in range(n):
    process(data[i], n)
```

### Memoization
```python
from functools import lru_cache

@lru_cache(maxsize=1024)
def expensive(x: int) -> int:
    return compute(x)
```

### Generator vs List
```python
# Bad — materializes whole list in memory
lines = [line for line in open("huge.txt")]
for line in lines: process(line)

# Good — streams one at a time
for line in open("huge.txt"):  # file is already iterable
    process(line)
```

## Anti-patterns

- ❌ Optimizing without measuring
- ❌ Micro-optimizing when the bottleneck is elsewhere
- ❌ Adding a cache without invalidation logic
- ❌ "Clever" code that's fast but unreadable
- ❌ Multithreading for CPU-bound Python (GIL) — use multiprocessing
- ❌ Premature pessimization (e.g. `time.sleep(0)` in hot loop "for safety")
- ❌ Assuming the profiler is wrong when results are surprising
