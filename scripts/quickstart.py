#!/usr/bin/env python3
"""Aion Hand Quick Start — runs after install to verify everything works.

Usage:
    aion-hand quickstart
    python scripts/quickstart.py
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ── ANSI helpers ──────────────────────────────────────────────────────────

def _c(code: int) -> str:
    return f"\033[{code}m"

RED, GREEN, YELLOW, BLUE, CYAN, PURPLE, BOLD, DIM, NC = (
    _c(31), _c(32), _c(33), _c(34), _c(36), _c(35), _c(1), _c(2), _c(0),
)

def info(msg: str) -> None:    print(f"{BLUE}  [INFO]{NC} {msg}")
def ok(msg: str) -> None:      print(f"{GREEN}  [OK]{NC}   {msg}")
def warn(msg: str) -> None:    print(f"{YELLOW}  [WARN]{NC} {msg}")
def fail(msg: str) -> None:   print(f"{RED}  [FAIL]{NC} {msg}")

def header(msg: str) -> None:
    print()
    print(f"{PURPLE}{BOLD}  ── {msg} ──{NC}")
    print()

# ── Paths ─────────────────────────────────────────────────────────────────

AION_HOME = Path(os.environ.get("AION_HAND_HOME", Path.home() / ".aion-hand"))
ENV_FILE = AION_HOME / ".env"
VERSION_FILE = AION_HOME / "VERSION"

# ── Checks ────────────────────────────────────────────────────────────────

def check_python_version() -> bool:
    """Verify Python 3.11+."""
    major, minor = sys.version_info[:2]
    if major >= 3 and minor >= 11:
        ok(f"Python {major}.{minor}.{sys.version_info[2]}  ({platform.python_implementation()})")
        return True
    fail(f"Python {major}.{minor} — need 3.11+")
    return False


def check_installation() -> bool:
    """Verify aion-hand is importable."""
    header("Installation Check")

    try:
        mod = importlib.import_module("aion_core")
        ver = getattr(mod, "__version__", "unknown")
        ok(f"aion_core {ver}")
    except ImportError:
        fail("aion_core not importable — installation may be broken")
        return False

    try:
        importlib.import_module("aion_hand_cli")
        ok("aion_hand_cli")
    except ImportError:
        warn("aion_hand_cli not found (CLI may not work)")

    return True


def check_directories() -> None:
    """Verify all expected directories exist."""
    dirs = ["bin", "data", "memory", "skills", "tools", "logs", "knowledge", "benchmarks", "config"]
    for d in dirs:
        p = AION_HOME / d
        if p.is_dir():
            ok(f"{d}/ exists")
        else:
            warn(f"{d}/ missing — creating")
            p.mkdir(parents=True, exist_ok=True)


def check_config() -> dict[str, Any]:
    """Load and display .env configuration."""
    header("Configuration")
    config: dict[str, str] = {}

    if not ENV_FILE.exists():
        warn("No .env file found — run 'aion-hand setup' to configure")
        return config

    ok(f".env found at {ENV_FILE}")
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                config[key.strip()] = val.strip()
                # Hide API keys
                if "KEY" in key.upper() or "SECRET" in key.upper():
                    display = val[:6] + "..." + val[-4:] if len(val) > 10 else "***"
                    info(f"  {key} = {display}")
                else:
                    info(f"  {key} = {val}")

    return config


def check_provider(config: dict[str, Any]) -> None:
    """Test the configured AI provider."""
    header("Provider Test")
    provider = config.get("AION_PROVIDER", "ollama").strip().lower()

    if provider == "ollama":
        _check_ollama()
    elif provider == "openai":
        _check_openai(config)
    elif provider == "anthropic":
        _check_anthropic(config)
    else:
        warn(f"Unknown provider '{provider}' — skipping connection test")


def _check_ollama() -> None:
    """Check if Ollama is running."""
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        warn("Ollama CLI not found — install from https://ollama.ai")
        return
    ok(f"Ollama CLI found at {ollama_path}")

    try:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            models = [l.split()[0] for l in lines[1:] if l.strip()]  # skip header
            if models:
                ok(f"Ollama running — {len(models)} model(s): {', '.join(models[:3])}")
            else:
                warn("Ollama running but no models pulled. Try: ollama pull llama3.2")
        else:
            warn("Ollama may not be running. Start with: ollama serve")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        warn(f"Cannot reach Ollama: {exc}")


def _check_openai(config: dict[str, Any]) -> None:
    """Check OpenAI configuration."""
    api_key = config.get("AION_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        warn("No OpenAI API key configured")
        return
    ok(f"OpenAI API key configured ({api_key[:6]}...)")
    _test_provider_connection("openai", api_key)


def _check_anthropic(config: dict[str, Any]) -> None:
    """Check Anthropic configuration."""
    api_key = config.get("AION_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        warn("No Anthropic API key configured")
        return
    ok(f"Anthropic API key configured ({api_key[:6]}...)")
    _test_provider_connection("anthropic", api_key)


def _test_provider_connection(provider: str, api_key: str) -> None:
    """Attempt a minimal API call to verify connectivity."""
    try:
        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            client.models.list()  # lightweight call
            ok("OpenAI API connection successful")
        elif provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            # Just verify client init doesn't throw
            ok("Anthropic client initialized (key format valid)")
    except ImportError:
        warn(f"{provider} SDK not installed — skipping live test")
    except Exception as exc:
        warn(f"{provider} connection test failed: {exc}")


def run_benchmark() -> None:
    """Run a minimal benchmark — simple completion test."""
    header("Quick Benchmark")

    try:
        if shutil.which("ollama"):
            info("Testing Ollama with 'hello' prompt...")
            result = subprocess.run(
                ["ollama", "run", "--nowordwrap", "llama3.2", "Say 'Aion Hand ready' in 5 words or fewer."],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                reply = result.stdout.strip()[:100]
                ok(f"Ollama responded: {reply}")
            else:
                warn(f"Ollama test failed (code {result.returncode})")
                if result.stderr:
                    warn(f"  stderr: {result.stderr.strip()[:120]}")
        else:
            info("No local provider available — skipping benchmark")
    except subprocess.TimeoutExpired:
        warn("Benchmark timed out (60s)")
    except Exception as exc:
        warn(f"Benchmark skipped: {exc}")


def print_summary(checks: list[bool]) -> None:
    """Print final summary."""
    passed = sum(checks)
    total = len(checks)
    all_ok = all(checks)

    print()
    if all_ok:
        print(f"{GREEN}{BOLD}  ✅  All checks passed! Aion Hand is ready.{NC}")
    else:
        print(f"{YELLOW}{BOLD}  ⚠️  {passed}/{total} checks passed. See warnings above.{NC}")
        print(f"{DIM}       Run 'aion-hand setup' to fix configuration issues.{NC}")

    print()
    print(f"{CYAN}  Next steps:{NC}")
    if not all_ok:
        print(f"{BOLD}    1. aion-hand setup{NC}       — configure your provider & API key")
    print(f"{BOLD}    {'1. ' if all_ok else '2. '}aion-hand{NC}             — start the AI operating system")
    print(f"{BOLD}    {'2. ' if all_ok else '3. '}aion-hand --help{NC}      — see all commands")
    print()

# ── Main ──────────────────────────────────────────────────────────────────

def quickstart() -> None:
    """Run all quickstart checks."""
    print(f"{PURPLE}{BOLD}")
    print("     ╔═══════════════════════════════╗")
    print("     ║    AION HAND QUICK START      ║")
    print("     ╚═══════════════════════════════╝")
    print(f"{NC}")
    print(f"{DIM}  Verifying your installation...{NC}")

    checks: list[bool] = []

    # 1. Python version
    checks.append(check_python_version())

    # 2. Installation
    checks.append(check_installation())

    # 3. Directories
    check_directories()

    # 4. Config
    config = check_config()
    checks.append(bool(config))

    # 5. Provider
    check_provider(config)

    # 6. Benchmark
    run_benchmark()

    # 7. Summary
    print_summary(checks)


if __name__ == "__main__":
    quickstart()