---
name: simplify-code
description: "Refactor for clarity: extract functions, remove dead code, rename for understanding. Smaller functions are easier to test and reason about."
version: 1.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [refactoring, clean-code, readability]
---

# Simplify Code

Use this skill when reviewing or refactoring existing code for clarity.

## Targets of Simplification

1. **Long functions** — extract cohesive blocks into named helpers
2. **Deep nesting** — early returns, guard clauses
3. **Duplicate logic** — extract shared function
4. **Poor names** — rename for clarity
5. **Dead code** — remove (git remembers)
6. **Comment-as-code** — replace comments with well-named functions
7. **God classes** — split by responsibility

## The Method

### 1. Read first
Don't refactor code you don't understand. Read it end-to-end. Run it.
Write a characterisation test if there isn't one.

### 2. One change at a time
- Extract ONE function
- Run tests
- Commit
- Repeat

### 3. Preserve behavior
Refactoring changes structure, not behavior. If tests change, you've
gone beyond refactoring — that's a rewrite.

### 4. Verify
After each step:
- All tests pass
- Linter passes
- Diff is small and reviewable

## Specific Refactorings

### Extract Function
```python
# Before
def process_order(order):
    # validate
    if not order.items:
        raise ValueError("empty order")
    if order.total < 0:
        raise ValueError("negative total")
    # apply discount
    if order.customer.is_vip:
        order.total *= 0.9
    # save
    order.save()
    return order

# After
def process_order(order):
    _validate_order(order)
    _apply_discount(order)
    _save_order(order)
    return order
```

### Replace Nested Conditional with Guard Clauses
```python
# Before
def get_payment(order):
    if order is not None:
        if order.is_paid:
            return order.payment
        else:
            return None
    else:
        return None

# After
def get_payment(order):
    if order is None:
        return None
    if not order.is_paid:
        return None
    return order.payment
```

### Rename
```python
# Bad
def calc(d, r, t):
    return d * (1 + r) ** t

# Good
def compound_interest(principal, rate, years):
    return principal * (1 + rate) ** years
```

## When NOT to Refactor

- Right before a release
- When you don't have tests
- When the "ugly" code is actually load-bearing (e.g. performance-critical)
- When the cost of refactoring exceeds the cost of living with it

## Anti-patterns

- ❌ Big-bang refactors (1000-line PRs)
- ❌ Refactoring + behavior change in one commit
- ❌ "Cleanup" commits that sneak in features
- ❌ Refactoring without tests
- ❌ Renaming public API without deprecation path
