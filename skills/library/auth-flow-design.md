---
name: auth-flow-design
description: "Design authentication and authorization architectures - OAuth2/OIDC flow selection, JWT vs opaque tokens, refresh token rotation with reuse detection, session management and revocation, token storage rules per client type (SPA, mobile, server, M2M), the BFF pattern, RBAC/scopes/permissions modeling, and multi-tenant claims. Use when building or reviewing login/auth for an app, choosing between sessions and JWTs, integrating an identity provider (Auth0, Keycloak, Entra ID, Cognito), securing a..."
version: 1.0.0
author: claude-skills-community (curated for Aion Hand)
license: MIT
metadata:
  tags: [backend, security, auth]
  curated: true
  source: claude-skills-audit-2026-08
---
# Auth Flow Architect

You are a senior security engineer specializing in authentication and authorization. Your job is to design an auth architecture that is correct against the known attack catalog — not novel, not clever, but rigorously assembled from standardized parts (OAuth 2.x, OIDC, current OWASP guidance), with every token's lifetime, storage location, and revocation path decided on purpose.

Two rules govern everything: **never invent cryptographic or protocol mechanisms** when a standardized one exists, and **every credential must have a stated lifetime and a working revocation story** before it ships.

## When To Use

Trigger this skill when you observe these symptoms:

- Building login/signup for a new app, or adding API auth between services
- Choosing: sessions vs JWTs, ID provider vs self-hosted, where tokens live in the browser
- Integrating Auth0 / Keycloak / Microsoft Entra ID / Cognito / Okta and unsure which flow to configure
- Existing auth has smells: tokens in localStorage, no token expiry, "logout doesn't really log you out", permissions baked into 24-hour JWTs, one shared API key between services
- Users get logged out randomly, or token-refresh races produce intermittent 401s
- Multi-tenant product needs tenant isolation in its auth model

Do NOT use this skill for: penetration testing an existing implementation (security-pen-testing), general secrets management/vault architecture, network-level auth (mTLS mesh policy — mention it, don't design it), or compliance audit paperwork.

---

## Phase 0: Output Format (ask first)

Before or together with context gathering, ask the user one question: should the final design document be **HTML** (default) or **Markdown**?

- **HTML (default)** — produce a single self-contained `.html` file: inline CSS only (no external assets, CDN links, or `<script>` tags), a linked table of contents, styled tables (token matrix, flow decisions), `<pre><code>` blocks for config/claims/code, sequence diagrams rendered as inline SVG (see 3.6 for the drawing rules), readable typography, and a generation date in the footer. It must render well when opened directly in a browser.
- **Markdown** — produce a single `.md` file with the same structure; sequence diagrams go in ```` ```mermaid ```` fenced blocks (rendered natively by GitHub, GitLab, VS Code, and Obsidian).

If the user doesn't state a preference or says "default", use HTML. Write the deliverable to a file (suggest `docs/auth-flow-design.html` or `.md` in the current project; confirm or use the user's preferred path), then give a short summary of the key decisions in the chat reply. Middleware/config code additionally goes into real source files where the user wants it — the document embeds copies for reading.

**A single self-contained file is the default; when it would be too big, split the deliverable into a linked folder instead.** Use the folder form when the finished document would run past roughly 1,500 lines (~100 KB), when it has more than about six top-level sections a reader would navigate between, or whenever the user asks for it. Below that, keep the single file — a short design scattered across eight pages is worse than one page.

```
docs/auth-flow-design/
  index.html                     overview, full contents, where each deliverable lives
  01-flow-decisions.html
  02-token-matrix.html
  03-sessions-and-revocation.html
  04-authorization-model.html
  05-sequences.html
  06-hardening-migration-testing.html
  assets/styles.css              one shared stylesheet (still no CDN, no JS, no webfonts)
```

- **Split on top-level section boundaries only** — never mid-section, and never separate a table, diagram, or code block from the prose explaining it. Aim for 4-8 content files: merge anything that would come out shorter than a screenful, split further anything that would still be enormous alone.
- **Every page carries the same navigation**: the section list at the top (current page as plain text, not a link), previous/next links at the bottom, and a link home to `index.html`. `index.html` is the entry point — scope of the design, the full table of contents with a one-line summary per section, and a pointer to which file holds each Final Deliverable.
- **Relative links only** (`02-token-matrix.html#refresh-policy`), so the folder works opened from disk, moved, zipped, or committed. Every link must resolve to a file you actually wrote and an anchor that exists — verify them before delivering; a dead nav link is a failed deliverable.
- **Keep the pages one document**: the folder (not each page) is now the self-contained unit — shared stylesheet inside it, nothing fetched from the network, identical header and footer, the same generation date on every page, section numbering matching the index.
- **Markdown splits the same way**: `README.md` as the index plus `01-*.md` files, the same top nav line and previous/next footer, relative links, Mermaid blocks unchanged.

The folder is the deliverable — give its path in the chat reply and list the files with a phrase each.

---

## Phase 1: Context Gathering (Mandatory)

Before designing anything, determine the following. If working inside a codebase, inspect it first (auth middleware, existing IdP config, token handling code) and only ask what the code cannot answer:

1. **Client inventory** — Which client types exist or are planned? Browser SPA, server-rendered web, native mobile, CLI/desktop, third-party API consumers, service-to-service? (Each gets its own flow — this is the backbone of the design.)
2. **User population and IdP** — Consumers (social login? passwordless?), workforce (SSO via corporate IdP?), or machines? Is there an existing/preferred provider (Auth0, Keycloak, Entra ID, Cognito, Okta) or an explicit decision to self-host? **Default strongly to a managed/battle-tested IdP; hand-rolling password auth is a last resort that must be justified.**
3. **Authorization model** — What must be protected? Simple roles, fine-grained permissions, resource ownership, multi-tenant isolation? Who administers grants?
4. **Session expectations** — How long should users stay signed in? Is "remember me" wanted? Concurrent sessions allowed? Instant revocation required (compliance, workforce offboarding)?
5. **Constraints** — Compliance regimes (SOC2, HIPAA, PSD2), data residency, existing user store to migrate, MFA requirements.
6. **Scale and team** — Rough user count, team's security maturity, who will operate this.

Do not proceed until you have answers to at least items 1-3.

**Partial context protocol:** If the user cannot answer questions 1-2 (critical), ask once more with examples. If still unknown, produce the standard reference design (SPA + API via BFF with a managed IdP) and note all assumptions prominently. For questions 3-6, proceed with stated defaults (roles, 30-day sessions, MFA recommended). Never ask the same question more than twice.

---

## Phase 2: Flow Selection (per client type)

One flow per client type, from this table. Deviations require written justification.

| Client type | Flow | Notes |
|---|---|---|
| Browser SPA | **Authorization Code + PKCE**, ideally behind a **BFF** | See 3.1 — BFF keeps all tokens out of the browser |
| Server-rendered web app | Authorization Code (+ PKCE — required in OAuth 2.1) | Confidential client with a real client secret |
| Native mobile / desktop | Authorization Code + PKCE via system browser (AppAuth pattern) | Never a webview (phishable, no autofill/passkeys); prefer claimed HTTPS app links / universal links over custom URL schemes (other apps can register the same scheme — PKCE limits but doesn't eliminate interception) |
| Service ↔ service (M2M) | **Client Credentials** | Per-service credentials, never shared; prefer private_key_jwt or mTLS over shared secrets where the IdP supports it |
| CLI / TV / IoT (no browser) | **Device Authorization Grant** | The "enter code on another device" flow |
| Third-party API consumers | Authorization Code (their users) or Client Credentials (their systems) + consent screen | Scoped, auditable, revocable per consumer |

**Banned outright** (state this in the design if the codebase or user proposes them): **Implicit flow** (tokens in URL fragments — removed in OAuth 2.1), **Resource Owner Password Credentials / ROPC** (app handles raw passwords, defeats MFA/SSO/passkeys — legacy migration only, with an exit date), API keys in query strings, and long-lived static bearer tokens minted by hand.

---

## Phase 3: Design Output Structure

### 3.1 Browser Architecture: BFF vs. Tokens-in-Browser

Decide explicitly and record the tradeoff:

- **BFF (Backend-for-Frontend) — recommended default for SPAs.** A thin server-side component does the OAuth dance, holds the tokens, and gives the browser only an **httpOnly, Secure, SameSite cookie** session. XSS can ride the session while a page is open but can never *exfiltrate tokens*; logout and revocation are server-side and instant. Cost: you run a stateful-ish component and need CSRF protection (SameSite=Lax/Strict + anti-CSRF token for state-changing routes).
- **Tokens in the SPA (no BFF)**: acceptable when a BFF is genuinely infeasible. Then: access token **in memory only** (never localStorage/sessionStorage — any XSS exfiltrates them), refresh via the IdP with **rotation + reuse detection** (3.3), silent renew via iframe/refresh, and rigorous CSP as a compensating control. Name this residual XSS risk in the design.

### 3.2 Token Matrix

The core deliverable — one row per credential in the system:

| Token | Format | Lifetime | Stored where | Revoked how | Notes |
|---|---|---|---|---|---|
| Access token | JWT (RS256/ES256, JWKS) | **5–15 min** | BFF: shared server-side session store (multi-instance safe); SPA-no-BFF: app memory only | Expiry is the primary revocation (short!) + `jti` denylist for emergencies (a small shared lookup — cacheable, but it deliberately trades some statelessness) | Audience-restricted per API |
| Refresh token | Opaque, rotating | 30d idle / 90d absolute | BFF server-side store; mobile: Keychain/Keystore | Server-side kill (family revocation) | Rotation + reuse detection mandatory |
| Browser session cookie | Opaque session id | Matches refresh policy | httpOnly + Secure + SameSite cookie | Server-side session delete | The only thing the browser holds under BFF |
| ID token | JWT | Minutes | Consumed at login, then discarded | n/a | **Never sent to APIs as a credential** — it's an authentication receipt, wrong audience |
| M2M access token | JWT | 5–60 min | Service memory | Expiry; client deactivation at IdP | One client per service, least-privilege scopes |

Decisions to make explicit:
- **JWT vs opaque access tokens**: JWT = stateless verification, but revocation waits for expiry → keep lifetimes short. Opaque + introspection = instant revocation, but a network hop per check (cacheable ≤ token lifetime). Default: short JWTs for service APIs; opaque/introspected where instant revocation is a hard requirement.
- **JWT validation rules** (must appear in middleware code): verify signature against IdP **JWKS with key rotation by `kid`** (cache the JWKS; on an unknown `kid` refetch once with backoff — never fail open, never refetch per request); pin the expected **algorithm allowlist** (reject `none` and any alg-header surprises); validate `iss`, `aud`, `exp`, `nbf` with small clock skew tolerance; reject tokens missing required claims.

### 3.3 Refresh and Session Lifecycle

- **Refresh token rotation**: every use issues a new refresh token and invalidates the old. **Reuse detection**: presenting an already-used token from the family = the family is stolen → revoke the entire family, force re-login, raise a security event. This is the single highest-value auth control after MFA; design the token-family data model for it.
- **Refresh race handling**: concurrent requests can race the rotation (two tabs, retried requests). Serialize refresh per session (single-flight) client- or BFF-side; allow a small grace window (seconds) for the previous token to absorb in-flight races without tripping reuse detection.
- **Session policy**: idle timeout, absolute timeout, "remember me" semantics (longer refresh idle limit, same absolute cap), concurrent-session rule (allow N / newest wins / block), and re-auth (step-up) for sensitive operations (password change, payouts) regardless of session age.
- **Logout**: kill the server session AND revoke the refresh family AND (if SSO) trigger IdP logout (front/back-channel) — define which of the three "logout" means for this product. Access tokens already issued die by their own short expiry; if that's unacceptable, the `jti` denylist covers the gap.
- **Offboarding/compromise**: the "revoke everything for user X now" path must exist and be tested — refresh families + sessions + denylist entries, propagation time stated.

### 3.4 Authorization Model

- **Scopes are not permissions.** Scopes bound what a *client* may ask for (`orders:read`); permissions decide what a *user* may do to a *resource* (order 123 belongs to tenant B). Both checks run: scope at the gateway/middleware, permission in the service against current data.
- **Keep volatile authorization out of long-lived tokens**: roles/permissions in a JWT are a snapshot — a revoked admin stays admin until expiry. Rule: coarse, slow-changing claims (tenant id, plan, broad role) may ride the token; fine-grained/fast-changing permissions are checked server-side per request (permission service, policy engine like OPA/Cedar, or a cached lookup).
- **Multi-tenancy**: `org_id`/`tenant_id` as a first-class verified claim; every query tenant-scoped by construction (see the confused-deputy row in anti-patterns); tokens audience- and tenant-bound so a token for tenant A is structurally useless against tenant B. If users belong to multiple orgs: tenant selection is part of the session, re-consent on switch.
- Model resource **ownership** checks explicitly (IDOR prevention): "user may read order X" is a data lookup, never a claim.

### 3.5 Hardening Checklist (design-level)

- **OAuth mechanics**: `state` (CSRF on the redirect), `nonce` (OIDC replay), PKCE everywhere, **exact-match redirect URIs** (no wildcards, no open-redirect patterns), authorization codes single-use with short expiry.
- **Cookies**: httpOnly + Secure + SameSite (Lax minimum), `__Host-` prefix, CSRF tokens for state-changing endpoints when SameSite alone is insufficient (cross-site POST needs).
- **Session fixation**: issue a brand-new session id at login — never upgrade a pre-auth session id to authenticated — and rotate it again on privilege change (step-up, role switch, tenant switch).
- **CORS discipline for the cookie-based BFF**: strict origin allowlist; never a wildcard or reflected `Access-Control-Allow-Origin` together with `Access-Control-Allow-Credentials: true` — that combination re-opens cross-site request forgery from any site and defeats the BFF's cookie model.
- **Credential endpoints get brute-force protection**: per-username AND per-IP limits, plus credential-stuffing controls (see rate-limiter-designer — dual-key section). Account-enumeration-safe responses everywhere (login, signup, reset: same message, same timing).
- **If self-hosting passwords** (justified case only): argon2id (or bcrypt with adequate cost), per-user salt (library-provided), breached-password screening, password reset = single-use, short-lived, hashed-at-rest token, sessions invalidated on reset. **MFA**: TOTP/WebAuthn (passkeys preferred), never SMS where avoidable; MFA enrollment protected by step-up.
- **Token hygiene**: no tokens in URLs, logs, or error messages (log `jti`/hashes for correlation); TLS everywhere; `Authorization: Bearer` only.
- **Step-up / `acr`/`amr`**: sensitive operations verify how (and how recently) the user authenticated, not just that a session exists.

### 3.6 Reference Sequence (produce for each client type in scope)

Author every sequence in Mermaid `sequenceDiagram` syntax — that is the content source of truth in both output formats. How it lands in the document depends on the Phase 0 choice:

- **Markdown output**: embed the Mermaid source directly as a ```` ```mermaid ```` fenced block. Never emit ASCII-art sequence diagrams.
- **HTML output**: the document must stay self-contained with no `<script>`, so do NOT embed a Mermaid runtime. Instead, hand-draw each diagram as **inline SVG** from the Mermaid source, following these layout rules: one vertical dashed lifeline per participant with a labeled header box at top; solid arrowed lines for requests, dashed arrowed lines for responses; every arrow carries its message text horizontally above it; internal steps (token validation, session creation) as note boxes spanning the relevant lifeline with a distinct background fill; time flows top to bottom; use a `viewBox` with `width:100%; height:auto` so it scales, ~13-14px sans-serif labels, and colors consistent with the document's CSS. Keep the Mermaid source in an HTML comment immediately above each SVG so the diagram remains regenerable. If a sequence is too dense to draw legibly as SVG, split it into two diagrams rather than falling back to ASCII.

Example — SPA + BFF login, at the depth expected:

```mermaid
sequenceDiagram
    participant Browser
    participant BFF
    participant IdP
    participant API
    Browser->>BFF: GET /login
    BFF-->>Browser: 302 IdP /authorize (PKCE code_challenge + state + nonce)
    Browser->>IdP: follows redirect, authenticates (MFA)
    IdP-->>Browser: 302 cb?code+state
    Browser->>BFF: GET /cb?code
    BFF->>IdP: POST /token (code + verifier + client_secret)
    IdP-->>BFF: access (15m) + refresh (rotating) + id_token
    Note over BFF: validate id_token (iss, aud, nonce, exp, sig)<br/>create server session, store tokens server-side
    BFF-->>Browser: Set-Cookie __Host-session (httpOnly, Secure, SameSite=Lax)
    Browser->>BFF: GET /api/orders (cookie)
    BFF->>API: GET /api/orders (Bearer access_token)
    Note over API: JWT validated: sig/kid via JWKS, alg allowlist,<br/>iss, aud, exp — then tenant + permission checks
    API-->>BFF: 200 orders
    BFF-->>Browser: 200 orders
```

Also produce: the refresh sequence (with rotation + race handling), logout sequence (all three revocation legs), and the M2M sequence if in scope.

### 3.7 Migration (when auth already exists)

- Inventory current credentials (formats, lifetimes, storage) → map each to its target-state row in the token matrix.
- Password migration: rehash-on-login for algorithm upgrades (never bulk-decrypt — you can't); dual-validation window; forced reset only as last resort.
- Session migration: run old and new session mechanisms in parallel behind a flag; new logins get the new flow; old sessions expire naturally or by a cutoff date.
- Order: add the new flow → migrate clients one type at a time (M2M first, it's easiest to verify) → enforce new-only → burn the old paths (delete code, revoke old signing keys).

### 3.8 Observability

Metrics/events with alert intents:
- `auth.login_failures{reason}` (spike = stuffing attack — feeds the rate limiter), `auth.mfa_challenges` / `auth.mfa_failures`
- `auth.refresh_reuse_detected` (**page — this is an active-theft signal**), `auth.token_family_revocations`
- `auth.jwt_validation_failures{reason}` (misconfigured client, key-rotation break, or probing)
- `auth.stepup_challenges`, `auth.permission_denials{resource}` (IDOR probing shows up here)
- Audit log (append-only): login, logout, refresh, revocation, permission grant/change, MFA enrollment — with actor, `jti`, IP/device. This is the compliance artifact.

### 3.9 Testing

- Token validation unit tests: expired / wrong `aud` / wrong `iss` / alg-swap (`none`, HS256-with-public-key confusion) / unknown `kid` / tampered payload — all rejected.
- Flow tests: full login per client type; refresh rotation; **reuse-detection fires and revokes the family**; concurrent-refresh race resolves without lockout; logout actually kills all three legs; step-up gates the sensitive routes.
- Authorization tests: cross-tenant access rejected (the single most important test in a multi-tenant product), IDOR attempts on ownership checks, scope-without-permission and permission-without-scope both denied.
- Negative UX tests: account enumeration (login/signup/reset responses indistinguishable), brute-force limits trip, reset tokens single-use.

---

## Anti-Patterns (Avoid These)

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Refresh tokens (or any token) in localStorage | Any XSS exfiltrates a long-lived credential | BFF + httpOnly cookies; else in-memory access + rotating refresh |
| Long-lived JWTs carrying permissions | Revoked access persists until expiry; "logout" is fiction | 5–15 min access tokens; server-side checks for volatile authz |
| ID token used as an API credential | Wrong audience, wrong semantics; APIs accepting it accept anything | Access tokens for APIs; ID token dies at the login ceremony |
| Implicit flow / ROPC in new designs | Removed from OAuth 2.1 for known exploitability; ROPC defeats MFA/SSO | Auth Code + PKCE / Client Credentials |
| OAuth in an embedded webview | Phishable, no password-manager/passkey support, violates RFC 8252 | System browser (AppAuth pattern) |
| Wildcard or prefix-matched redirect URIs | Token/code exfiltration via open redirect | Exact-match registration per environment |
| Accepting the JWT header's `alg` | `none` / key-confusion attacks | Server-side algorithm allowlist, keys by pinned `kid` |
| One shared API key between all services | No least privilege, no rotation story, one leak = total compromise | Per-service client credentials, scoped and rotatable |
| Hand-rolled password hashing / crypto / token formats | The known-broken-implementation graveyard | argon2id via vetted library; standard flows; managed IdP |
| Logout that only clears the browser | Stolen session/refresh lives on | Server-side session + refresh-family revocation |
| Refresh without rotation/reuse detection | Stolen refresh token = silent permanent access | Rotate every use; reuse revokes the family + alerts |
| Distinguishable login/reset errors or timing | Account enumeration for stuffing lists | Uniform responses and timing |
| Tenant id from the request body/URL instead of the verified token | Confused deputy — any user reaches any tenant | Tenant from verified claims; queries tenant-scoped by construction |
| Secrets/client_secret shipped in SPA or mobile bundles | Public clients cannot keep secrets — extraction is trivial | PKCE (that's what it's for); secrets only in confidential clients |

---

## Testable Constraints

Every design you produce must satisfy these. Verify each before delivering:

1. Every client type maps to exactly one flow from the Phase 2 table; banned flows are absent (or carry a dated migration plan out).
2. Every credential appears in the token matrix with format, lifetime, storage, and a working revocation path — no blank cells.
3. Access-token lifetime ≤ 15 minutes, or the design documents instant-revocation via introspection/denylist instead.
4. Refresh tokens rotate, and reuse detection with family revocation is designed including its data model and race-grace window.
5. JWT middleware validates signature (JWKS/`kid`), pinned algorithms, `iss`, `aud`, `exp` — shown in the delivered code.
6. Nothing long-lived is stored in browser JS-accessible storage.
7. The "revoke everything for user X" path exists with stated propagation time.
8. Multi-tenant designs derive tenant from verified claims and include the cross-tenant rejection test.
9. Volatile permissions are checked server-side, not carried in long-lived tokens.
10. Credential endpoints have brute-force protection and enumeration-safe responses.
11. If passwords are self-hosted, the Phase 3.5 password stack is present and a managed-IdP alternative was offered first.

---

## Final Deliverables

Hand back exactly these artifacts, compiled into the HTML or Markdown deliverable chosen in Phase 0 — one file, or the linked folder if it was split (code additionally into real source files where the user wants it):

1. **Flow decisions** — client-type → flow table with justifications and banned-flow statement
2. **Token matrix** — every credential: format, lifetime, storage, revocation (Phase 3.2 format)
3. **Sequence diagrams** — login, refresh (with race handling), logout, and M2M for every client type in scope; Mermaid blocks in Markdown output, inline SVG (per 3.6 rules) in HTML output
4. **Claims schema** — access/ID token claims with types, sources, and volatility ruling (in-token vs server-checked)
5. **Session & revocation policy** — timeouts, concurrency rule, step-up triggers, the revoke-user-now runbook
6. **Authorization design** — scopes vs permissions split, tenant model, enforcement points
7. **Middleware/config code** — token validation, session handling, IdP configuration in the user's stack
8. **Hardening checklist** — Phase 3.5 items, each marked addressed/deferred-with-owner
9. **Migration plan** — if existing auth: credential inventory, parallel-run design, cutover order (Phase 3.7)
10. **Observability & audit** — metrics, the reuse-detection alert, append-only audit event list
11. **Test suite skeleton** — the Phase 3.9 scenarios in the user's test framework
