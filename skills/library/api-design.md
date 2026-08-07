---
name: api-design
description: "Design REST/JSON APIs: resource-oriented, predictable, versioned, with clear errors. Consistency beats cleverness."
version: 1.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [api, rest, design, http]
---

# API Design

Use this skill when designing or reviewing HTTP/JSON APIs.

## Principles

1. **Resource-oriented.** URLs name resources (`/users/42/orders`), not actions (`/getUserOrders`).
2. **HTTP verbs are the actions.** GET = read, POST = create, PATCH = update, DELETE = delete.
3. **Predictable.** Same patterns everywhere. If `/users` returns a list, so does `/orders`.
4. **Versioned.** `/v1/users` — never break clients silently.
5. **Stateless.** Each request contains all info needed. No server-side sessions.
6. **Idempotent where possible.** `PUT /users/42` should give the same result no matter how many times called.

## URL Conventions

- Plural nouns: `/users`, `/orders`, `/products`
- Hierarchy for sub-resources: `/users/42/orders`
- Lowercase, kebab-case for multi-word: `/password-resets`
- Trailing slash: pick one and be consistent (no trailing slash is more common)
- Query params for filtering/sorting/pagination: `/orders?status=paid&sort=-created_at&limit=20`

## Status Codes

| Code | When |
|------|------|
| 200 OK | Successful GET, PUT, PATCH, DELETE |
| 201 Created | Successful POST |
| 204 No Content | Successful DELETE (no body) |
| 400 Bad Request | Malformed request (validation error) |
| 401 Unauthorized | Not authenticated |
| 403 Forbidden | Authenticated but not allowed |
| 404 Not Found | Resource doesn't exist |
| 409 Conflict | Version conflict, duplicate |
| 422 Unprocessable Entity | Semantic validation error |
| 429 Too Many Requests | Rate limited |
| 500 Internal Server Error | Bug in server |
| 503 Service Unavailable | Maintenance / overload |

## Response Format

**Success:**
```json
{
  "data": { ... } | [ ... ],
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 142
  }
}
```

**Error:**
```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Email is required",
    "details": [
      { "field": "email", "code": "REQUIRED" }
    ],
    "request_id": "req_abc123"
  }
}
```

## Pagination

- Offset/limit: `?page=2&per_page=20` — simple, but slow for large offsets
- Cursor: `?after=eyJpZCI6MTQyfQ==` — fast, but no random access
- Always include `total` for offset pagination, `has_more` for cursor

## Versioning

- URL versioning: `/v1/users` — most common, easiest to debug
- Header versioning: `Accept: application/vnd.api+json;version=1` — cleaner URLs, harder to test
- Don't version on body — caching breaks

## Anti-patterns

- ❌ Verbs in URLs: `/createUser`, `/getOrderById`
- ❌ Returning 200 with `{"error": "..."}` body
- ❌ Different patterns for different resources
- ❌ Breaking changes without a new version
- ❌ HTTP 500 for user errors (use 4xx)
- ❌ Returning internal stack traces in production
- ❌ Undocumented status codes
- ❌ Inconsistent error formats across endpoints
