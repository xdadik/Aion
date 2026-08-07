---
name: security-hardening
description: "Apply defense-in-depth: validate input, sanitize output, least privilege, audit log, secret rotation. Never trust user input."
version: 1.0.0
author: Aion Hand
license: MIT
metadata:
  tags: [security, hardening, defense-in-depth]
---

# Security Hardening

Use this skill when designing, reviewing, or auditing systems for security.

## Core Principles

1. **Never trust input.** Validate type, length, format, range. Whitelist > blacklist.
2. **Defense in depth.** Multiple layers: network, OS, app, data.
3. **Least privilege.** Give the minimum access needed to do the job.
4. **Fail safe.** On error, deny — don't allow.
5. **Audit everything.** Log who did what, when, from where.
6. **Rotate secrets.** Tokens expire; keys rotate; never commit secrets.

## Input Validation

```python
# Bad
def get_user(user_id):
    return db.query(f"SELECT * FROM users WHERE id = {user_id}")

# Good
def get_user(user_id: int) -> User:
    if not isinstance(user_id, int) or user_id < 1:
        raise ValidationError("user_id must be a positive integer")
    return db.query("SELECT * FROM users WHERE id = %s", (user_id,))
```

- Type-check at boundaries (API, CLI, file load)
- Validate before processing
- Reject early, fail closed
- Sanitize output (escape HTML, parameterize SQL)

## Common Vulnerabilities

### SQL Injection
- ❌ String concatenation
- ✅ Parameterized queries / ORM

### XSS
- ❌ `innerHTML = userInput`
- ✅ Text content / proper escaping
- ✅ Content-Security-Policy header

### CSRF
- ❌ State-changing GET requests
- ✅ SameSite cookies + CSRF tokens

### Path Traversal
- ❌ `open(user_input)`
- ✅ Validate path is within allowed root
- ✅ Use `Path.resolve()` and check prefix

### Command Injection
- ❌ `os.system(user_input)`
- ✅ `subprocess.run(["cmd", user_input], shell=False)`

### SSRF
- ❌ Fetch arbitrary URLs from user input
- ✅ Allowlist domains / block private IP ranges

### Insecure Deserialization
- ❌ `pickle.loads(user_data)`
- ✅ JSON with schema validation

## Authentication & Authorization

- Hash passwords with bcrypt/argon2 — never SHA1/MD5
- Use constant-time comparison for tokens
- JWT: short-lived access token + long-lived refresh token
- Rate limit auth endpoints (10/min/IP)
- MFA for sensitive operations
- Log all auth events

## Secrets Management

- ❌ Hardcoded in source
- ❌ In `.env` files committed to git
- ❌ In CI logs
- ✅ Environment variables (CI)
- ✅ Vault / SSM / Secrets Manager (prod)
- ✅ `.gitignore` for `.env`, `*.key`, `secrets.*`

## Logging & Monitoring

Log:
- Auth events (login success/failure, token refresh)
- Authorization decisions (especially denials)
- Data access (especially for sensitive data)
- Config changes
- Privileged operations

Don't log:
- Passwords (even hashed)
- Full tokens (mask: `ghp_***1234`)
- PII (mask: `j***@example.com`)
- Credit card numbers (mask: `**** **** **** 4242`)

## Dependency Security

- `pip-audit` / `npm audit` / `cargo audit` in CI
- Pin versions (lockfiles)
- Review new dependencies (popularity, maintenance, security history)
- Remove unused deps

## Anti-patterns

- ❌ "We'll add security later"
- ❌ Rolling your own crypto
- ❌ Trusting the client for authz
- ❌ Storing secrets in code
- ❌ Catching and swallowing exceptions
- ❌ Verbose error messages to clients
- ❌ Disabling certificate verification (`verify=False`)
