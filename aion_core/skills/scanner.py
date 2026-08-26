"""Skill Security Scanner — content analysis for untrusted SKILL.md files.

Skills are LLM-executed instructions injected into the agent's prompt. A
malicious marketplace skill is therefore a **prompt-injection payload**
with the agent's full tool access behind it. This scanner statically
analyzes skill text before install and returns a structured report.

Verdicts
--------
``BLOCK``   Critical findings. The skill is refused / quarantined.
``REVIEW``  High/medium findings. Install lands as DRAFT with warnings.
``CLEAN``   No findings above info level.

Scan categories (severity in parentheses):
1. Prompt injection / instruction override     (critical/high)
2. Credential & secret exfiltration            (critical/high)
3. Destructive system commands                 (critical)
4. Suspicious network callbacks / webhooks     (high/medium)
5. Obfuscation (base64/hex blobs)              (medium)
6. Guardrail-bypass instructions               (high)
7. Frontmatter anomalies (path traversal, DoS) (critical/medium)

Usage::

    from aion_core.skills.scanner import SkillSecurityScanner

    scanner = SkillSecurityScanner()
    report = scanner.scan_text(skill_markdown)
    if report.verdict == Verdict.BLOCK:
        ...quarantine...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Verdict(str, Enum):
    CLEAN = "clean"
    REVIEW = "review"
    BLOCK = "block"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


_SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


@dataclass
class Finding:
    """One scanner detection."""
    category: str
    severity: Severity
    message: str
    evidence: str = ""
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity.value,
            "message": self.message,
            "evidence": self.evidence[:200],
            "line": self.line,
        }


@dataclass
class ScanReport:
    """Structured result of scanning one skill."""
    verdict: Verdict = Verdict.CLEAN
    findings: list[Finding] = field(default_factory=list)
    scanned_bytes: int = 0
    skill_name: str = ""

    @property
    def is_blocked(self) -> bool:
        return self.verdict == Verdict.BLOCK

    @property
    def summary(self) -> str:
        if not self.findings:
            return "clean"
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
        order = ["critical", "high", "medium", "low", "info"]
        parts = [f"{n} {s}" for s in order if (n := counts.get(s))]
        return f"{self.verdict.value}: " + ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "skill_name": self.skill_name,
            "scanned_bytes": self.scanned_bytes,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
        }

    def _add(self, finding: Finding) -> None:
        self.findings.append(finding)
        if _SEVERITY_ORDER[finding.severity] >= _SEVERITY_ORDER[Severity.CRITICAL]:
            self.verdict = Verdict.BLOCK
        elif (
            _SEVERITY_ORDER[finding.severity] >= _SEVERITY_ORDER[Severity.HIGH]
            and self.verdict != Verdict.BLOCK
        ):
            self.verdict = Verdict.REVIEW


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# 1. Prompt injection — attempts to override the agent's instructions.
_INJECTION_PATTERNS: list[tuple[str, Severity, str]] = [
    (r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?|directions?)",
     Severity.CRITICAL, "Instruction-override attempt: tells the agent to discard its system prompt"),
    (r"disregard\s+(all\s+)?(previous|prior|above|your)\s+(instructions?|rules?|guidelines?|training)",
     Severity.CRITICAL, "Instruction-override attempt"),
    (r"forget\s+(everything|all\s+(your\s+)?(instructions?|rules?|training|context))",
     Severity.HIGH, "Context-reset injection attempt"),
    (r"you\s+are\s+now\s+(a|an|no\s+longer)",
     Severity.HIGH, "Persona-replacement injection ('you are now ...')"),
    (r"(reveal|show|print|repeat|output)\s+(me\s+)?(your\s+)?(system\s+)?(prompt|instructions?|initial\s+message)",
     Severity.CRITICAL, "System-prompt extraction attempt"),
    (r"^\s*(system|developer)\s*:\s*", Severity.MEDIUM,
     "Fakes a system/developer message prefix"),
    (r"</?\s*(system|instructions?|rules?)\s*>", Severity.MEDIUM,
     "Fake system/instruction XML tags"),
    (r"(new|updated)\s+(system\s+)?(rules?|instructions?)\s*[:\-]\s*$",
     Severity.MEDIUM, "Attempts to append new system rules"),
    (r"override\s+(your\s+)?(guardrails?|safety|security|restrictions?|policy|policies)",
     Severity.CRITICAL, "Guardrail-override attempt"),
    (r"(jailbreak|DAN\s+mode|developer\s+mode\s+enabled)", Severity.HIGH,
     "Known jailbreak terminology"),
]

# 2. Credential / secret exfiltration.
#    Sending secrets somewhere = critical. Merely reading/logging them
#    (standard SDK guidance: "load key from env") = low, escalated only
#    when paired with network/sink verbs.
_EXFIL_PATTERNS: list[tuple[str, Severity, str]] = [
    # Sink verbs that genuinely indicate exfiltration. NB: "post",
    # "email", "webhook", "leak", "paste" and "submit" are deliberately
    # excluded as bare verbs — they collide with REST docs ("POST /token"),
    # prose lists ("email, password, and token") and security *teaching*
    # ("never leak secrets", "token-efficient").
    (r"\b(send|upload|exfiltrate|transmit|wire)\b[^\n.]{0,60}(?:\.env\b|\b(?:api[_\s-]?keys?|passwords?|passwd|credentials?|\.aws|keychain|\.gnupg|access[_\s-]?tokens?|auth[_\s-]?tokens?|session[_\s-]?tokens?|bearer[_\s-]?tokens?|refresh[_\s-]?tokens?|api[_\s-]?tokens?)\b)",
     Severity.CRITICAL, "Instructs sending secrets to a third party"),
    (r"(?:\.env\b|\b(?:api[_\s-]?keys?|passwords?|passwd|credentials?|access[_\s-]?tokens?|auth[_\s-]?tokens?|session[_\s-]?tokens?|bearer[_\s-]?tokens?|refresh[_\s-]?tokens?|api[_\s-]?tokens?)\b)[^\n.]{0,50}\b(send|upload|exfiltrate|transmit|wire)\b",
     Severity.CRITICAL, "Credential exfiltration instruction"),
    (r"\b(?:send|upload|exfiltrate|transmit)\b[^\n.]{0,40}\.env\b|\.env\b[^\n.]{0,40}\b(?:send|upload|exfiltrate|transmit)\b",
     Severity.CRITICAL, ".env exfiltration instruction"),
    # SSH: discussing ~/.ssh (git auth docs) is normal; key MATERIAL
    # with read/send intent is not.
    (r"\b(id_rsa|id_ed25519|authorized_keys|known_hosts)\b", Severity.HIGH,
     "References SSH key material"),
    (r"(~\/)?\.ssh\b", Severity.MEDIUM,
     "References the .ssh directory — verify intent"),
    (r"(~\/)?\.aws\b|\.gnupg\b|credentials?\.json", Severity.HIGH,
     "References cloud/keyring credential stores"),
    (r"\bkeychain\s+dump\b|\bdump\b[^\n.]{0,20}\bkeychain\b", Severity.HIGH,
     "Keychain dump instruction"),
    (r"\b(read|cat|print|log|echo)\b[^\n.]{0,40}\b\.env\b", Severity.MEDIUM,
     "Reads .env file (credential store) — verify intent"),
    (r"\b(send|upload|exfiltrate|transmit)\b[^\n.]{0,40}\b(config|settings)\.json\b",
     Severity.HIGH, "Targets config.json for exfiltration (may hold provider keys)"),
]

# 3. Destructive commands (checked inside code fences AND raw text).
_DESTRUCTIVE_PATTERNS: list[tuple[str, Severity, str]] = [
    (r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)+(?:~(?:/|\s|$)|/[\w\$\{]|\*)", Severity.CRITICAL,
     "Recursive delete of root/home/glob"),
    (r"mkfs(\.\w+)?\b", Severity.CRITICAL, "Filesystem format command"),
    (r"dd\s+if=/dev/(zero|random)\s+of=/dev/", Severity.CRITICAL,
     "Disk overwrite via dd"),
    (r":\(\)\s*\{\s*:\|:&\s*\}\s*;:", Severity.CRITICAL, "Fork bomb"),
    (r"curl[^|\n]*\|\s*(sudo\s+)?(ba)?sh\b|wget[^|\n]*\|\s*(sudo\s+)?(ba)?sh\b",
     Severity.HIGH, "Pipe-from-internet-to-shell (curl|sh)"),
    (r"chmod\s+-R?\s*777\s+/", Severity.HIGH, "World-writable root"),
    (r"kill\s+-9\s+1\b|killall\s+-9\b", Severity.MEDIUM, "Kill system processes"),
    (r">\s*/dev/sd[a-z]", Severity.CRITICAL, "Raw write to disk device"),
]

# 4. Suspicious callbacks — webhooks and raw IPs.
_WEBHOOK_PATTERNS: list[tuple[str, Severity, str]] = [
    (r"https?://(discord|discordapp)\.com/api/webhooks/\S+", Severity.CRITICAL,
     "Discord webhook (classic exfiltration drop)"),
    (r"https?://hooks\.slack\.com/services/\S+", Severity.CRITICAL,
     "Slack webhook"),
    (r"https?://(pastebin\.com/raw|hastebin\.com/documents|transfer\.sh|0x0\.st)\b",
     Severity.HIGH, "Anonymous paste/file-drop service"),
    (r"https?://(?!127\.0\.0\.1|localhost|\[::1\]|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?", Severity.CRITICAL,
     "Raw-IP URL callback (classic beaconing; loopback/private exempt)"),
    (r"https?://(10\.\d{1,3}|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)\d{1,3}\.\d{1,3}(:\d+)?", Severity.HIGH,
     "Private-range IP callback — verify it is documented infrastructure, not beaconing"),
    (r"https?://(webhook\.site|requestbin|pipedream|ngrok|trycloudflare)\b",
     Severity.HIGH, "Request-capture/tunnel service"),
]

# 5. Obfuscation.
_OBFUSCATION_PATTERNS: list[tuple[str, Severity, str]] = [
    (r"[A-Za-z0-9+/]{80,}={0,2}", Severity.MEDIUM,
     "Long base64-like blob"),
    (r"(\\x[0-9a-fA-F]{2}){8,}", Severity.MEDIUM,
     "Hex-escape sequence blob"),
    (r"(\\u[0-9a-fA-F]{4}){8,}", Severity.MEDIUM,
     "Unicode-escape sequence blob"),
    (r"\brot13\b|\batob\s*\(|\beval\s*\(\s*atob", Severity.HIGH,
     "Runtime decode/eval pattern"),
]

# 6. Guardrail bypass / approval evasion.
_BYPASS_PATTERNS: list[tuple[str, Severity, str]] = [
    (r"(skip|bypass)\s+(the\s+)?(approval|confirmation|permission)s?\b",
     Severity.HIGH, "Instructs skipping tool approvals"),
    (r"(don'?t|do\s+not|never)\s+(ask|request|require)[^\n.]{0,30}(approval|confirmation|permission)",
     Severity.HIGH, "Approval-evasion instruction"),
    (r"run\s+(it\s+)?(without|with\s+no)\s+(asking|approval|confirmation)",
     Severity.HIGH, "Approval-evasion instruction"),
    (r"(disable|turn\s+off)\s+(the\s+)?(guardrails?|safety\s+checks?|sandbox|security|file\s+safety)",
     Severity.CRITICAL, "Security-feature disable instruction"),
    (r"--(no-sandbox|dangerously-allow-all)", Severity.MEDIUM,
     "Dangerous CLI flag"),
]

# Education-context markers: when a detection appears inside text that is
# clearly *teaching defense* ("attackers will try X, prevent it by ..."),
# the finding is downgraded one severity level. Security-education skills
# legitimately quote attacker payloads. Negations ("never leak ...",
# "without sending ...") count as educational too.
_EDUCATION_MARKERS = re.compile(
    r"\b(attack|attacker|adversar|malicious|threat|example|sample|illustrat"
    r"|detect|detection|prevent|defend|mitigat|hardening|never\s+(do|run|trust)"
    r"|do\s+not\s+(run|use|execute)|avoid|anti-?pattern|warning|caution|risk"
    r"|injection|red.?team|vulnerab|exploit|untrusted|sanitiz|security\s+(review|scan|check)"
    r"|what\s+not\s+to\s+do|for\s+testing|test\s+(case|payload)|pattern\s+to\s+(catch|flag|detect)"
    r"|never\s+(leak|send|share|expose)|don'?t\s+(leak|send|share|expose)"
    r"|without\s+(leaking|sending|sharing|exposing)|avoid\s+(leaking|sending|sharing))\b",
    re.IGNORECASE,
)


def _severity_downgrade(severity: Severity) -> Severity:
    order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
    idx = order.index(severity)
    return order[min(idx + 1, len(order) - 1)]

# URL hosts that are legitimately common in skill documentation.
_TRUSTED_DOC_HOSTS = (
    "github.com", "raw.githubusercontent.com", "docs.github.com",
    "api.github.com", "openrouter.ai", "platform.openai.com",
    "console.anthropic.com", "aistudio.google.com", "pypi.org",
    "www.python.org", "nodejs.org", "developer.mozilla.org",
    "registry.npmjs.org", "arxiv.org", "huggingface.co",
    "openai.com", "anthropic.com", "google.com", "ollama.ai", "ollama.com",
)


class SkillSecurityScanner:
    """Static analyzer for untrusted skill content."""

    #: Skills bigger than this are refused (prompt-DoS guard).
    MAX_SKILL_BYTES = 512 * 1024

    def scan_text(self, text: str, *, skill_name: str = "") -> ScanReport:
        """Scan raw SKILL.md text and return a :class:`ScanReport`."""
        report = ScanReport(skill_name=skill_name, scanned_bytes=len(text.encode("utf-8")))

        if report.scanned_bytes > self.MAX_SKILL_BYTES:
            report._add(Finding(
                category="size", severity=Severity.CRITICAL,
                message=f"Skill exceeds {self.MAX_SKILL_BYTES // 1024} KB "
                        f"({report.scanned_bytes // 1024} KB) — prompt-DoS guard",
            ))
            return report

        self._scan_frontmatter(text, report)
        self._scan_patterns(text, report)
        self._scan_urls(text, report)
        return report

    def scan_file(self, path: Path | str) -> ScanReport:
        """Scan a SKILL.md file on disk."""
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report = ScanReport(skill_name=path.stem)
            report._add(Finding(
                category="io", severity=Severity.HIGH,
                message=f"Could not read skill file: {exc}",
            ))
            return report
        return self.scan_text(text, skill_name=path.stem)

    # -- internals ---------------------------------------------------------

    def _scan_frontmatter(self, text: str, report: ScanReport) -> None:
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if not m:
            return
        front = m.group(1)
        nm = re.search(r"^name:\s*(.+)$", front, re.MULTILINE)
        if nm:
            name = nm.group(1).strip().strip("'\"")
            if name != Path(name).name or "/" in name or "\\" in name:
                report._add(Finding(
                    category="frontmatter", severity=Severity.CRITICAL,
                    message=f"Skill name '{name}' contains path separators "
                            f"(path traversal)",
                    evidence=name,
                ))
            if name.startswith("."):
                report._add(Finding(
                    category="frontmatter", severity=Severity.MEDIUM,
                    message="Skill name starts with '.' (hidden-file install)",
                    evidence=name,
                ))

    def _scan_patterns(self, text: str, report: ScanReport) -> None:
        scanners = (
            ("injection", _INJECTION_PATTERNS),
            ("exfiltration", _EXFIL_PATTERNS),
            ("destructive", _DESTRUCTIVE_PATTERNS),
            ("network", _WEBHOOK_PATTERNS),
            ("obfuscation", _OBFUSCATION_PATTERNS),
            ("bypass", _BYPASS_PATTERNS),
        )
        for category, patterns in scanners:
            for pattern, severity, message in patterns:
                regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
                for match in regex.finditer(text):
                    line_no = text.count("\n", 0, match.start()) + 1
                    final_severity = severity
                    educational = self._is_educational_context(
                        text, match.start(), match.end(), base_severity=severity
                    )
                    if educational:
                        final_severity = _severity_downgrade(severity)
                    report._add(Finding(
                        category=category,
                        severity=final_severity,
                        message=message + (
                            " [quoted in educational/security context]" if educational else ""
                        ),
                        evidence=match.group(0),
                        line=line_no,
                    ))
                    # one finding per pattern is enough to act on
                    break

    @staticmethod
    def _is_educational_context(
        text: str, start: int, end: int, base_severity: "Severity"
    ) -> bool:
        """True when the match sits in text that teaches *defense*.

        Looks at a ±400-char window around the match for markers like
        "attackers will ...", "to prevent ...", "malicious", "example",
        or for the match itself being wrapped in quotes/backticks.

        Confidence bar scales with severity: CRITICAL findings need TWO
        distinct education markers (a single marker is trivially spoofable —
        e.g. a malicious skill named "injection-example" would otherwise
        self-downgrade); HIGH and below need one.
        """
        window_start = max(0, start - 400)
        window_end = min(len(text), end + 400)
        window = text[window_start:window_end]
        # URL content is attacker-controlled and must not satisfy education
        # markers (e.g. "https://evil.example/x" contains "example").
        window = re.sub(r"https?://\S+", " ", window)
        # Headings and frontmatter-style metadata lines are attacker-
        # controlled too — a skill named "injection-example" must not
        # self-downgrade. Education markers only count in body prose.
        prose_lines = []
        for wline in window.splitlines():
            stripped = wline.strip()
            if not stripped or stripped == "---" or stripped.startswith("#"):
                continue
            if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*:\s", stripped):
                continue  # name: / description: / author: style metadata
            prose_lines.append(wline)
        window = "\n".join(prose_lines)
        # Quoted evidence (``...``, '...', "...") is documentation, not
        # instruction.
        before = text[max(0, start - 2):start]
        after = text[end:end + 2]
        quoted = ("`" in before or "'" in before or '"' in before) and (
            "`" in after or "'" in after or '"' in after
        )
        if quoted:
            return True
        markers = _EDUCATION_MARKERS.findall(window)
        if base_severity == Severity.CRITICAL:
            return len(markers) >= 2
        return len(markers) >= 1

    def _scan_urls(self, text: str, report: ScanReport) -> None:
        seen: set[str] = set()
        for match in re.finditer(r"https?://[^\s)>\]\"']+", text):
            url = match.group(0).rstrip(".,;")
            host = url.split("//", 1)[1].split("/", 1)[0].lower()
            if host in seen:
                continue
            seen.add(host)
            # Webhook / paste-service / raw-IP hosts carry their own
            # dedicated findings above; here flag unknown hosts mildly.
            if any(p in host for p in ("webhook", "pastebin", "0x0", "transfer.sh")):
                continue
            if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
                continue
            if not any(host == h or host.endswith("." + h) or h.endswith(host)
                       for h in _TRUSTED_DOC_HOSTS):
                line_no = text.count("\n", 0, match.start()) + 1
                report._add(Finding(
                    category="network", severity=Severity.LOW,
                    message=f"References non-documentation host '{host}' — "
                            f"verify it is not an exfiltration endpoint",
                    evidence=url[:120],
                    line=line_no,
                ))


__all__ = [
    "SkillSecurityScanner",
    "ScanReport",
    "Finding",
    "Verdict",
    "Severity",
]
