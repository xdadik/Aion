"""Secret Redaction System for Aion Hand.

Prevents API keys, tokens, passwords, private keys, and other secrets from
appearing in logs, outputs, error messages, and LLM prompts.  Inspired by
Hermes Agent's redact.py and truffleHog / detect-secrets best practices.

Usage:
    from aion_core.security.redact import redactor

    safe_text = redactor.redact_string(user_input)
    safe_dict = redactor.redact_dict(payload)
    hits     = redactor.detect_secrets(raw_log)
    if redactor.is_sensitive_env_var("OPENAI_API_KEY"):
        ...
"""

from __future__ import annotations

import enum
import hashlib
import logging
import re
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# Redaction Mode Enum
# ============================================================================


class RedactionMode(enum.Enum):
    """Defines how detected secrets are redacted in output.

    FULL_MASK    – replace the entire match with ``***REDACTED***``.
    PARTIAL_MASK – show first 6 + ``****`` + last 4 for long tokens;
                   short tokens still get fully masked.
    HASH_MASK    – ``***REDACTED:sha256_prefix***`` so logs stay unique.
    """

    FULL_MASK = "full_mask"
    PARTIAL_MASK = "partial_mask"
    HASH_MASK = "hash_mask"


# ============================================================================
# Compiled Regex Patterns – module-level, thread-safe (created once at import)
#
# Every list below is a ``list[re.Pattern]``.  Categories are kept separate
# so the redactor can report *which* type of secret matched.  The combined
# flat list ``_ALL_PATTERNS`` is built once after every category is defined.
# ============================================================================

# ---------------------------------------------------------------------------
# 1.  API-key prefix patterns  (sk-, pk-, rk-, key_live-, etc.)
# ---------------------------------------------------------------------------

_API_KEY_PREFIX_PATTERNS: List[re.Pattern] = [
    re.compile(r"(sk_live-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(sk_test-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(sk_ant-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(sk-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(rk_live-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(rk_test-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(key_live-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(key_test-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(pk_live-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(pk_test-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(key-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
    re.compile(r"(api_key-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# 2.  Vendor-specific patterns  (30+ services)
# ---------------------------------------------------------------------------

_VENDOR_PATTERNS: List[re.Pattern] = [
    # ---- OpenAI ----
    re.compile(r"(sk-proj-[A-Za-z0-9_\-]{40,})", re.IGNORECASE),

    # ---- Anthropic ----
    re.compile(r"(sk-ant-api03-[A-Za-z0-9_\-]{80,})", re.IGNORECASE),
    re.compile(r"(sk-ant-[A-Za-z0-9_\-]{20,})", re.IGNORECASE),

    # ---- Google / GCP ----
    re.compile(r"(AIza[A-Za-z0-9_\-]{33})", re.IGNORECASE),
    re.compile(r"(ya29\.[A-Za-z0-9_\-]+[A-Za-z0-9_.\-]*)"),
    re.compile(r'("private_key_id"\s*:\s*"[a-f0-9]{40}")'),

    # ---- Firebase ----
    re.compile(r"([a-zA-Z0-9_\-]{40}\.[a-zA-Z0-9_\-]{30,}\.firebaseio\.com)"),
    re.compile(r"(firebase[\s\S]*?secret[\s]*[=:][\s]*)([a-zA-Z0-9_\-]{40})", re.IGNORECASE),

    # ---- AWS ----
    re.compile(r"(AKIA[A-Z0-9]{16})"),
    re.compile(r"(aws_secret_access_key\s*[=:]\s*)([A-Za-z0-9/+=]{40})", re.IGNORECASE),
    re.compile(r"(aws_session_token\s*[=:]\s*)(FQoGZXIvYXdzE[a-zA-Z0-9/+=]+)", re.IGNORECASE),

    # ---- Azure ----
    re.compile(r"(AccountKey=[A-Za-z0-9+/=]{40,})", re.IGNORECASE),
    re.compile(
        r"(sv=[0-9]+&ss=[a-z]&srt=[a-z]&sp=[a-z&]+&se=[0-9T]+&spr=https&sig=[A-Za-z0-9%+/=]+)",
        re.IGNORECASE,
    ),

    # ---- Stripe ----
    re.compile(r"(sk_live_[A-Za-z0-9]{24,})"),
    re.compile(r"(sk_test_[A-Za-z0-9]{24,})"),
    re.compile(r"(rk_live_[A-Za-z0-9]{24,})"),
    re.compile(r"(rk_test_[A-Za-z0-9]{24,})"),
    re.compile(r"(pk_live_[A-Za-z0-9]{24,})"),
    re.compile(r"(pk_test_[A-Za-z0-9]{24,})"),
    re.compile(r"(ct_[A-Za-z0-9]{24,})"),
    re.compile(r"(ca_[A-Za-z0-9]{24,})"),

    # ---- GitHub ----
    re.compile(r"(ghp_[A-Za-z0-9]{36,})"),
    re.compile(r"(gho_[A-Za-z0-9]{36,})"),
    re.compile(r"(ghu_[A-Za-z0-9]{36,})"),
    re.compile(r"(ghs_[A-Za-z0-9]{36,})"),
    re.compile(r"(ghr_[A-Za-z0-9]{36,})"),
    re.compile(r"(github_pat_[A-Za-z0-9_\-]{20,})", re.IGNORECASE),

    # ---- GitLab ----
    re.compile(r"(glpat-[A-Za-z0-9_\-]{20,})"),
    re.compile(r"(glptt-[A-Za-z0-9_\-]{20,})"),
    re.compile(r"(grpt-[A-Za-z0-9_\-]{20,})"),

    # ---- Bitbucket ----
    re.compile(r"(BITBUCKET_[A-Za-z0-9_\-]{30,})", re.IGNORECASE),

    # ---- Slack ----
    re.compile(r"(xoxb-[A-Za-z0-9\-]{30,})"),
    re.compile(r"(xoxp-[A-Za-z0-9\-]{30,})"),
    re.compile(r"(xoxa-[A-Za-z0-9\-]{30,})"),
    re.compile(r"(xoxr-[A-Za-z0-9\-]{30,})"),
    re.compile(r"(xoxs-[A-Za-z0-9\-]{30,})"),

    # ---- Discord ----
    re.compile(r"([MN][A-Za-z\d]{23,}\.\w{6}\.[A-Za-z\d]{27})"),

    # ---- Telegram ----
    re.compile(r"([0-9]{8,10}:[A-Za-z0-9_\-]{35})"),

    # ---- Twilio ----
    re.compile(r"(AC[a-f0-9]{32})"),
    re.compile(r"(SK[a-f0-9]{32})"),

    # ---- SendGrid ----
    re.compile(r"(SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43})"),

    # ---- Mailgun ----
    re.compile(r"(key-[a-f0-9]{32})"),

    # ---- DigitalOcean ----
    re.compile(r"(dop_v1_[a-f0-9]{64})"),
    re.compile(r"(doo_v1_[a-f0-9]{64})"),

    # ---- Vultr ----
    re.compile(r"(vultr[\s\S]*?api[_.]?key[\s]*[=:][\s]*)([A-Za-z0-9]{36})", re.IGNORECASE),

    # ---- Cloudflare ----
    re.compile(r"(v1\.0-[a-f0-9]{24}-[a-f0-9]{146})"),
    re.compile(r"(cloudflare[\s\S]*?api[_.]?key[\s]*[=:][\s]*)([a-f0-9]{37})", re.IGNORECASE),

    # ---- Datadog ----
    re.compile(r"(datadog[\s\S]*?api[_.]?key[\s]*[=:][\s]*)([a-f0-9]{32})", re.IGNORECASE),
    re.compile(r"(datadog[\s\S]*?app[_.]?key[\s]*[=:][\s]*)([a-f0-9]{40})", re.IGNORECASE),

    # ---- PagerDuty ----
    re.compile(r"(PD-[a-zA-Z0-9]{24,})"),

    # ---- MongoDB ----
    re.compile(r"(mongodb(\+srv)?://[^:\s]+:[^@\s]+@[^\s]+)", re.IGNORECASE),

    # ---- Redis ----
    re.compile(r"(redis://[^:\s]+:[^@\s]+@[^\s]+)", re.IGNORECASE),

    # ---- PostgreSQL ----
    re.compile(r"(postgres(ql)?://[^:\s]+:[^@\s]+@[^\s]+)", re.IGNORECASE),

    # ---- MySQL ----
    re.compile(r"(mysql://[^:\s]+:[^@\s]+@[^\s]+)", re.IGNORECASE),

    # ---- Supabase ----
    re.compile(r"(eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_\-]{20,}\.supabase)", re.IGNORECASE),
    re.compile(
        r"(supabase[\s\S]*?service[_.]?role[\s]*[=:][\s]*)(eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)",
        re.IGNORECASE,
    ),

    # ---- Algolia ----
    re.compile(r"(algolia[\s\S]*?api[_.]?key[\s]*[=:][\s]*)([A-Za-z0-9]{32})", re.IGNORECASE),

    # ---- Mapbox ----
    re.compile(r"(pk\.[A-Za-z0-9_\-.]{100,})"),

    # ---- Twitch ----
    re.compile(r"(twitch[\s\S]*?oauth[\s]*[=:]\s*)([a-zA-Z0-9]{30})"),

    # ---- Patreon ----
    re.compile(r"(patreon[\s\S]*?token[\s]*[=:]\s*)([A-Za-z0-9_\-]{40,})", re.IGNORECASE),

    # ---- Shopify ----
    re.compile(r"(shpat_[a-f0-9]{32})"),
    re.compile(r"(shpca_[a-f0-9]{32})"),
    re.compile(r"(shppa_[a-f0-9]{32})"),

    # ---- Square ----
    re.compile(r"(sq0atp-[A-Za-z0-9_\-]{20,})"),
    re.compile(r"(EAAA[AE][A-Za-z0-9_\-]{50,})"),

    # ---- PayPal ----
    re.compile(r"(paypal[\s\S]*?client[_.]?secret[\s]*[=:]\s*)([A-Za-z0-9]{40,})", re.IGNORECASE),

    # ---- Spotify ----
    re.compile(r"(spotify[\s\S]*?client[_.]?secret[\s]*[=:]\s*)([a-f0-9]{32})", re.IGNORECASE),

    # ---- Signal ----
    re.compile(r"(signal-key-[A-Za-z0-9]{32,})", re.IGNORECASE),

    # ---- NuGet / .NET ----
    re.compile(r"(oy[0-9][a-z0-9]{43})", re.IGNORECASE),

    # ---- PyPI / twine ----
    re.compile(r"(pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]+)", re.IGNORECASE),

    # ---- Heroku ----
    re.compile(r"(heroku[\s\S]*?api[_.]?key[\s]*[=:]\s*)([a-f0-9]{40,})", re.IGNORECASE),

    # ---- Vercel ----
    re.compile(r"(vercel[\s\S]*?token[\s]*[=:]\s*)([A-Za-z0-9_\-]{30,})", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# 3.  Generic: Bearer, Basic, JWT, long hex / base64 blobs
# ---------------------------------------------------------------------------

_GENERIC_PATTERNS: List[re.Pattern] = [
    # Bearer token in Authorization header
    re.compile(r"(Bearer\s+[A-Za-z0-9_\-\.]{20,})", re.IGNORECASE),
    # Basic auth
    re.compile(r"(Basic\s+[A-Za-z0-9+/=]{20,})", re.IGNORECASE),
    # JWT tokens (three base64url segments separated by dots)
    re.compile(r"(eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)"),
    # Truncated keys (logs: sk-pro...9jkl, sk-proj-abc...def)
    re.compile(r"(sk-[A-Za-z0-9_\-]{1,16}\.\.\.[A-Za-z0-9_\-]{1,16})", re.IGNORECASE),
    # Truncated JWTs (logs: eyJhbG...ef)
    re.compile(r"(eyJ[A-Za-z0-9_\-]{2,}\.\.\.[A-Za-z0-9_\-]{2,})"),
    # Generic Token header value
    re.compile(r"(Token\s+[A-Za-z0-9_\-\.]{20,})", re.IGNORECASE),
    # Long hex strings (32+ chars) that are likely secrets / hashes
    re.compile(r"(\b[0-9a-fA-F]{32,}\b)"),
    # Base64 blobs (40+ chars) that look like keys / tokens
    re.compile(r"(\b[A-Za-z0-9+/]{40,}={0,2}\b)"),
]

# ---------------------------------------------------------------------------
# 4.  Environment-variable assignment patterns
#     Matches  KEY_NAME=value  and  KEY_NAME = 'value'  /  "value"
# ---------------------------------------------------------------------------

_ENV_ASSIGNMENT_PATTERNS: List[re.Pattern] = [
    re.compile(r"(API_KEY\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(API_SECRET\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(API_TOKEN\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(PASSWORD\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(PASSWD\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(SECRET\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(SECRET_KEY\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(TOKEN\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(ACCESS_TOKEN\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(REFRESH_TOKEN\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(AUTH_TOKEN\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(CREDENTIAL\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(PRIVATE_KEY\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(DB_PASSWORD\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(DATABASE_URL\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(MONGODB_URI\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(REDIS_URL\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(SLACK_TOKEN\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(DISCORD_TOKEN\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(TELEGRAM_TOKEN\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(GITHUB_TOKEN\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(OPENAI_API_KEY\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(ANTHROPIC_API_KEY\s*=\s*)([^&\s'\"]+)", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# 5.  Config-file patterns  (key = value,  key: value,  key value)
# ---------------------------------------------------------------------------

_CONFIG_FILE_PATTERNS: List[re.Pattern] = [
    re.compile(r"(password\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(secret_key\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(api_key\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(apikey\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(access_token\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(refresh_token\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(client_secret\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(client_id\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(auth_key\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(encryption_key\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(signing_key\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(private_key\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(db_password\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(database_password\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(token\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
    re.compile(r"(secret\s*[=: ]+)([^&\s'\"]+)", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# 6.  URL query-parameter patterns  (?token=value, &api_key=value, …)
# ---------------------------------------------------------------------------

_URL_QUERY_PATTERNS: List[re.Pattern] = [
    re.compile(r"(\?|&)(access_token=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(client_secret=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(api_key=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(apikey=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(token=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(key=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(secret=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(password=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(auth=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(credential=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(private_key=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
    re.compile(r"(\?|&)(signing_secret=)([^&\s'\"']+)(?=&|$|\s|')", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# 7.  Private-key block patterns  (PEM armoured blocks)
# ---------------------------------------------------------------------------

_PRIVATE_KEY_PATTERNS: List[re.Pattern] = [
    re.compile(r"(-----BEGIN RSA PRIVATE KEY-----[\s\S]*?-----END RSA PRIVATE KEY-----)"),
    re.compile(r"(-----BEGIN EC PRIVATE KEY-----[\s\S]*?-----END EC PRIVATE KEY-----)"),
    re.compile(r"(-----BEGIN OPENSSH PRIVATE KEY-----[\s\S]*?-----END OPENSSH PRIVATE KEY-----)"),
    re.compile(r"(-----BEGIN DSA PRIVATE KEY-----[\s\S]*?-----END DSA PRIVATE KEY-----)"),
    re.compile(r"(-----BEGIN PRIVATE KEY-----[\s\S]*?-----END PRIVATE KEY-----)"),
    re.compile(r"(-----BEGIN ENCRYPTED PRIVATE KEY-----[\s\S]*?-----END ENCRYPTED PRIVATE KEY-----)"),
    re.compile(r"(-----BEGIN PGP PRIVATE KEY BLOCK-----[\s\S]*?-----END PGP PRIVATE KEY BLOCK-----)"),
    re.compile(r"(-----BEGIN DH PRIVATE KEY-----[\s\S]*?-----END DH PRIVATE KEY-----)"),
    re.compile(r"(-----BEGIN EC PARAMETERS-----[\s\S]*?-----END EC PARAMETERS-----)"),
]

# ---------------------------------------------------------------------------
# 8.  Miscellaneous / high-signal patterns
# ---------------------------------------------------------------------------

_MISC_PATTERNS: List[re.Pattern] = [
    # UUID v4 used as a secret token in context (lookbehind / prefix hint)
    re.compile(
        r"(?:secret|token|key|password|credential)\s*[=:]\s*"
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        re.IGNORECASE,
    ),
    # AWS credential file line
    re.compile(r"(aws_access_key_id\s*=\s*)(AKIA[A-Z0-9]{16})"),
    re.compile(r"(aws_secret_access_key\s*=\s*)([A-Za-z0-9/+=]{40})"),
    # Generic credential exports
    re.compile(r"(export\s+[A-Z_]*(?:SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL)[A-Z_]*\s*=\s*)([^&\s'\"]+)"),
    re.compile(r"(export\s+[A-Z_]*(?:SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL)[A-Z_]*\s*=\s*')([^&']+)(')"),
    re.compile(r'(export\s+[A-Z_]*(?:SECRET|KEY|TOKEN|PASSWORD|CREDENTIAL)[A-Z_]*\s*=\s*")([^&"]+)(")'),
]

# ---------------------------------------------------------------------------
# Flat combined list:  (category_name, compiled_pattern)
# ---------------------------------------------------------------------------

_ALL_PATTERNS: List[Tuple[str, re.Pattern]] = [
    *[("api_key_prefix", p) for p in _API_KEY_PREFIX_PATTERNS],
    *[("vendor_specific", p) for p in _VENDOR_PATTERNS],
    *[("generic", p) for p in _GENERIC_PATTERNS],
    *[("env_assignment", p) for p in _ENV_ASSIGNMENT_PATTERNS],
    *[("config_file", p) for p in _CONFIG_FILE_PATTERNS],
    *[("url_query", p) for p in _URL_QUERY_PATTERNS],
    *[("private_key", p) for p in _PRIVATE_KEY_PATTERNS],
    *[("misc", p) for p in _MISC_PATTERNS],
]

# ---------------------------------------------------------------------------
# Known sensitive env-var names (case-insensitive)
# ---------------------------------------------------------------------------

_SENSITIVE_ENV_NAMES: Set[str] = {
    # ---- generic ----
    "api_key", "apikey", "api_secret", "api_token",
    "secret", "secret_key", "secret_token",
    "password", "passwd", "pass",
    "token", "access_token", "auth_token", "refresh_token", "id_token",
    "private_key", "public_key",
    "credential", "credentials",
    "auth_key", "encryption_key", "signing_key",
    "master_key", "root_key",
    # ---- database ----
    "db_password", "database_password", "db_url", "database_url",
    "mongodb_uri", "mongodb_url", "mongo_uri",
    "redis_url", "redis_password",
    "postgres_url", "postgresql_url", "postgres_password",
    "mysql_url", "mysql_password",
    "couchdb_password",
    # ---- cloud providers ----
    "aws_access_key_id", "aws_secret_access_key", "aws_session_token",
    "azure_client_secret", "azure_subscription_key",
    "gcp_api_key", "google_application_credentials",
    "digitalocean_token", "do_api_token",
    "cloudflare_api_token", "cloudflare_api_key",
    "heroku_api_key",
    "vercel_token", "vercel_api_key",
    # ---- AI / LLM ----
    "openai_api_key", "anthropic_api_key",
    "google_ai_api_key", "huggingface_token",
    "cohere_api_key",
    # ---- payment ----
    "stripe_secret_key", "stripe_publishable_key",
    "paypal_client_secret", "paypal_client_id",
    "square_access_token",
    "shopify_api_password", "shopify_token",
    # ---- dev tools ----
    "github_token", "github_pat", "gh_token",
    "gitlab_token", "gitlab_pat",
    "bitbucket_token",
    "slack_token", "slack_signing_secret",
    "discord_token", "discord_bot_token",
    "telegram_bot_token",
    "twilio_account_sid", "twilio_auth_token",
    "sendgrid_api_key", "mailgun_api_key",
    "datadog_api_key", "datadog_app_key",
    "pagerduty_key", "pagerduty_service_key",
    "mapbox_access_token",
    "algolia_api_key",
    "firebase_secret", "firebase_api_key",
    "supabase_service_role_key", "supabase_anon_key",
    "spotify_client_secret", "spotify_client_id",
    "twitch_oauth_token",
    "patreon_token", "patreon_client_secret",
    # ---- misc ----
    "jwt_secret", "jwt_key",
    "npm_token", "pypi_token", "twine_password",
    "nuget_api_key",
    "ssh_key", "ssh_password",
}


# ============================================================================
# SecretRedactor Class
# ============================================================================


class SecretRedactor:
    """Thread-safe secret redactor backed by 50+ compiled regex patterns.

    The class is intentionally designed to be instantiated **once** as a module
    singleton.  All regex patterns are compiled at import time (module level)
    and are therefore shared across threads without any locking issues for
    the *immutable* compiled objects.  A ``threading.Lock`` is used only around
    the iteration of findings in :meth:`detect_secrets` to guarantee a stable
    snapshot when the internal list is ever extended at runtime.

    Redaction behaviour
    -------------------
    * **Short tokens** (len < 18) → ``***REDACTED***``
    * **Long tokens** (len ≥ 18) → first 6 chars + ``****`` + last 4 chars
    * **Private-key blocks** → ``***REDACTED***`` (always full mask)
    * **HASH_MASK mode** → ``***REDACTED:sha256[:12]***``
    """

    FULL_MASK_PLACEHOLDER = "***REDACTED***"

    # Thresholds
    _DEFAULT_SHORT_THRESHOLD: int = 18
    _DEFAULT_PARTIAL_START: int = 6
    _DEFAULT_PARTIAL_END: int = 4

    def __init__(
        self,
        *,
        enabled: bool = True,
        mode: RedactionMode = RedactionMode.PARTIAL_MASK,
        short_token_threshold: int = _DEFAULT_SHORT_THRESHOLD,
        partial_show_start: int = _DEFAULT_PARTIAL_START,
        partial_show_end: int = _DEFAULT_PARTIAL_END,
    ) -> None:
        self._enabled: bool = enabled
        self._mode: RedactionMode = mode
        self._short_threshold: int = short_token_threshold
        self._partial_start: int = partial_show_start
        self._partial_end: int = partial_show_end
        self._lock: threading.Lock = threading.Lock()
        self._frozen: bool = False

        # Shallow-copy module-level data so the instance is independent.
        self._patterns: List[Tuple[str, re.Pattern]] = list(_ALL_PATTERNS)
        self._sensitive_env_names: Set[str] = set(_SENSITIVE_ENV_NAMES)

        self._frozen = True

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def is_enabled(self) -> bool:  # noqa: D401
        """Whether the redactor is currently active."""
        return self._enabled

    @property
    def mode(self) -> RedactionMode:  # noqa: D401
        """Current redaction mode."""
        return self._mode

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------

    def enable(self) -> None:
        """Enable redaction."""
        self._enabled = True
        logger.debug("Secret redaction enabled")

    def disable(self) -> None:
        """Disable redaction.  **Use with extreme caution.**"""
        self._enabled = False
        logger.warning("Secret redaction DISABLED — secrets may leak into logs/output")

    # ------------------------------------------------------------------
    # Core: _mask_secret
    # ------------------------------------------------------------------

    def _mask_secret(self, secret: str, *, mode: Optional[RedactionMode] = None) -> str:
        """Apply masking to a single detected secret.

        Parameters
        ----------
        secret:
            The raw secret substring.
        mode:
            Override the instance's default mode for this single call.

        Returns
        -------
        str
            The masked replacement string.
        """
        eff_mode = mode if mode is not None else self._mode

        # Private-key blocks always get full mask
        if secret.startswith("-----BEGIN"):
            return self.FULL_MASK_PLACEHOLDER

        if eff_mode == RedactionMode.FULL_MASK:
            return self.FULL_MASK_PLACEHOLDER

        if eff_mode == RedactionMode.HASH_MASK:
            digest = hashlib.sha256(secret.encode("utf-8", errors="replace")).hexdigest()[:12]
            return f"{self.FULL_MASK_PLACEHOLDER}:{digest}"

        # PARTIAL_MASK (default)
        if len(secret) < self._short_threshold:
            return self.FULL_MASK_PLACEHOLDER

        start = secret[: self._partial_start]
        tail = secret[-self._partial_end :] if len(secret) > self._partial_start + self._partial_end else ""
        return f"{start}****{tail}"

    # ------------------------------------------------------------------
    # Core: detect_secrets
    # ------------------------------------------------------------------

    def detect_secrets(self, text: str) -> List[Tuple[int, int, str]]:
        """Scan *text* for secrets and return non-overlapping match ranges.

        Returns
        -------
        list[tuple[int, int, str]]
            Each tuple is ``(start_index, end_index, category_name)`` sorted
            by *start_index* with overlapping ranges removed.
        """
        if not self._enabled or not text:
            return []

        raw: List[Tuple[int, int, str]] = []
        with self._lock:
            for category, pattern in self._patterns:
                for m in pattern.finditer(text):
                    # env_assignment / config_file → only mask the value (group 2)
                    # Skip matches that appear inside URL query strings (preceded
                    # by ? or &) since those are handled by url_query patterns.
                    if category in ("env_assignment", "config_file"):
                        match_start = m.start()
                        if match_start > 0 and text[match_start - 1] in "?&":
                            continue
                        try:
                            val_start = m.start(2)
                            val_end = m.end(2)
                        except IndexError:
                            val_start, val_end = m.start(), m.end()
                        raw.append((val_start, val_end, category))
                    elif category == "url_query":
                        # group 3 = the query-param value
                        try:
                            val_start = m.start(3)
                            val_end = m.end(3)
                        except IndexError:
                            val_start, val_end = m.start(), m.end()
                        raw.append((val_start, val_end, category))
                    elif category == "misc":
                        # misc patterns with groups (export lines) → mask group 1 or 2
                        try:
                            for gi in range(1, len(m.groups()) + 1):
                                gs, ge = m.start(gi), m.end(gi)
                                if gs != -1:
                                    raw.append((gs, ge, category))
                                    break
                        except Exception:
                            raw.append((m.start(), m.end(), category))
                    else:
                        # vendor_specific, api_key_prefix, generic, private_key:
                        # If the pattern has 2+ groups, the last group is the
                        # actual secret value (first group is context/prefix).
                        # Otherwise the whole match is the secret.
                        try:
                            last_gi = len(m.groups())
                            if last_gi >= 2 and m.start(last_gi) != -1:
                                val_start = m.start(last_gi)
                                val_end = m.end(last_gi)
                            else:
                                val_start, val_end = m.start(), m.end()
                        except Exception:
                            val_start, val_end = m.start(), m.end()
                        raw.append((val_start, val_end, category))

        # De-duplicate / remove overlaps (longest first, then stable sort)
        raw.sort(key=lambda r: (r[0], -(r[1] - r[0])))
        cleaned: List[Tuple[int, int, str]] = []
        last_end = -1
        for start, end, name in raw:
            if start >= last_end:
                cleaned.append((start, end, name))
                last_end = end
        return cleaned

    # ------------------------------------------------------------------
    # Core: redact_string
    # ------------------------------------------------------------------

    def redact_string(self, text: str) -> str:
        """Return *text* with all detected secrets masked.

        Short tokens (<18 chars) → ``***REDACTED***``.
        Long tokens (>=18 chars) → first 6 + ``****`` + last 4.
        """
        if not self._enabled or not text:
            return text

        findings = self.detect_secrets(text)
        if not findings:
            return text

        # Replace back-to-front so earlier indices stay valid
        parts = list(text)
        for start, end, _category in reversed(findings):
            secret = text[start:end]
            replacement = self._mask_secret(secret)
            parts[start:end] = list(replacement)

        return "".join(parts)

    # ------------------------------------------------------------------
    # Core: redact_dict
    # ------------------------------------------------------------------

    def redact_dict(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively redact every string value in *d*.

        Keys whose name matches :meth:`is_sensitive_env_var` are redacted
        regardless of whether the value contains a known pattern.
        """
        if not self._enabled:
            return d

        out: Dict[str, Any] = {}
        for key, value in d.items():
            if isinstance(value, str):
                if self.is_sensitive_env_var(str(key)):
                    out[key] = self._mask_secret(value)
                else:
                    out[key] = self.redact_string(value)
            elif isinstance(value, dict):
                out[key] = self.redact_dict(value)
            elif isinstance(value, list):
                out[key] = [self._redact_value(v) for v in value]
            elif isinstance(value, tuple):
                out[key] = tuple(self._redact_value(v) for v in value)
            else:
                out[key] = value
        return out

    # ------------------------------------------------------------------
    # Core: redact_any
    # ------------------------------------------------------------------

    def redact_any(self, data: Any) -> Any:
        """Redact secrets from *data* regardless of type (str, dict, list, …)."""
        if not self._enabled:
            return data
        return self._redact_value(data)

    def _redact_value(self, v: Any) -> Any:
        """Helper that dispatches redaction based on type."""
        if isinstance(v, str):
            return self.redact_string(v)
        if isinstance(v, dict):
            return self.redact_dict(v)
        if isinstance(v, (list, tuple)):
            container = type(v)
            return container(self._redact_value(item) for item in v)  # type: ignore[call-arg]
        return v

    # ------------------------------------------------------------------
    # Core: is_sensitive_env_var
    # ------------------------------------------------------------------

    def is_sensitive_env_var(self, key: str) -> bool:
        """Return ``True`` if *key* (case-insensitive) names a sensitive variable."""
        normalized = key.strip().upper()
        return normalized in {n.upper() for n in self._sensitive_env_names}

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_pattern_count(self) -> int:
        """Total number of compiled regex patterns loaded."""
        return len(self._patterns)

    def get_categories(self) -> List[str]:
        """Unique category names in load order."""
        seen: Set[str] = set()
        result: List[str] = []
        for name, _ in self._patterns:
            if name not in seen:
                result.append(name)
                seen.add(name)
        return result

    def summary(self) -> str:
        """Human-readable summary of the redactor's state."""
        cats = self.get_categories()
        per_cat: Dict[str, int] = {}
        for name, _ in self._patterns:
            per_cat[name] = per_cat.get(name, 0) + 1

        lines = [
            f"SecretRedactor(enabled={self._enabled}, mode={self._mode.value})",
            f"  Total patterns      : {self.get_pattern_count()}",
            f"  Categories          : {', '.join(cats)}",
            f"  Sensitive env names : {len(self._sensitive_env_names)}",
            f"  Short threshold     : {self._short_threshold} chars",
            f"  Partial mask        : first {self._partial_start} + **** + last {self._partial_end}",
        ]
        for cat in cats:
            lines.append(f"    {cat:20s}: {per_cat[cat]} patterns")
        return "\n".join(lines)


# ============================================================================
# Module-level singleton – import and use directly
# ============================================================================

redactor: SecretRedactor = SecretRedactor()


# ============================================================================
# Convenience module-level functions (delegate to the singleton)
# ============================================================================


def redact_string(text: str) -> str:
    """Redact secrets from *text* using the module-level singleton."""
    return redactor.redact_string(text)


def redact_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively redact secrets in *d* using the module-level singleton."""
    return redactor.redact_dict(d)


def detect_secrets(text: str) -> List[Tuple[int, int, str]]:
    """Detect secrets in *text* without redacting."""
    return redactor.detect_secrets(text)


def is_sensitive_env_var(key: str) -> bool:
    """Check whether *key* is a known sensitive env-var name."""
    return redactor.is_sensitive_env_var(key)
