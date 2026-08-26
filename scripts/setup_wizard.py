#!/usr/bin/env python3
"""Aion Hand Setup Wizard — interactive first-run configuration.

Usage:
    aion-hand setup
    python scripts/setup_wizard.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
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
def fail(msg: str) -> None:   print(f"{RED}  [ERR]{NC}  {msg}")
def step(msg: str) -> None:
    print()
    print(f"{PURPLE}{BOLD}  ── Step {msg} ──{NC}")
    print()

# ── Paths ─────────────────────────────────────────────────────────────────

AION_HOME = Path(os.environ.get("AION_HAND_HOME", Path.home() / ".aion-hand"))
ENV_FILE = AION_HOME / ".env"
CONFIG_FILE = AION_HOME / "config" / "settings.json"

# ── Provider definitions ──────────────────────────────────────────────────

PROVIDERS = {
    "ollama": {
        "name": "Ollama (Local)",
        "description": "Free, private, runs on your machine. No API key needed.",
        "needs_key": False,
        "default_model": "llama3.2",
        "install_hint": "Install from https://ollama.ai  |  brew install ollama  |  curl -fsSL https://ollama.ai/install.sh | sh",
    },
    "openai": {
        "name": "OpenAI",
        "description": "GPT-4o, GPT-4o-mini. Requires API key.",
        "needs_key": True,
        "default_model": "gpt-4o-mini",
        "install_hint": "Get a key at https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "name": "Anthropic",
        "description": "Claude 3.5 Sonnet, Claude 3.5 Haiku. Requires API key.",
        "needs_key": True,
        "default_model": "claude-3-5-sonnet-20241022",
        "install_hint": "Get a key at https://console.anthropic.com/",
    },
    "google": {
        "name": "Google AI (Gemini)",
        "description": "Gemini 1.5 Pro, Gemini 1.5 Flash. Requires API key.",
        "needs_key": True,
        "default_model": "gemini-1.5-flash",
        "install_hint": "Get a key at https://aistudio.google.com/apikey",
    },
    "openrouter": {
        "name": "OpenRouter (400+ models, 1 key)",
        "description": "One key unlocks GPT, Claude, Gemini, Llama, DeepSeek, Qwen, Mistral and more — including free models. Best value for a single credential.",
        "needs_key": True,
        "default_model": "meta-llama/llama-4-scout",
        "install_hint": "Get a key at https://openrouter.ai/keys (free models available)",
    },
}

# ── Input helpers ─────────────────────────────────────────────────────────

def prompt(text: str, default: str = "") -> str:
    """Prompt user for input with optional default."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{CYAN}{BOLD}  > {text}{suffix}: {NC}").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        print(f"{YELLOW}  Setup cancelled.{NC}")
        sys.exit(0)
    return value or default


def prompt_choice(text: str, options: dict[str, str], default: str = "") -> str:
    """Prompt user to choose from a list of options."""
    keys = list(options.keys())
    print()
    for i, key in enumerate(keys, 1):
        marker = f" {GREEN}(default)" if key == default else ""
        print(f"    {BOLD}{i}.{NC} {options[key]}{marker}")
    print()

    while True:
        raw = prompt(text, default)
        # Accept number or key name
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        elif raw.lower() in [k.lower() for k in keys]:
            return keys[[k.lower() for k in keys].index(raw.lower())]
        print(f"  {RED}Invalid choice. Enter a number or provider name.{NC}")


def prompt_yes_no(text: str, default: bool = True) -> bool:
    """Yes/No prompt."""
    hint = "Y/n" if default else "y/N"
    raw = prompt(f"{text} ({hint})", "y" if default else "n")
    return raw.lower().startswith("y")

# ── Steps ────────────────────────────────────────────────────────────────

def step_welcome() -> None:
    print(f"{PURPLE}{BOLD}")
    print("  ╔═════════════════════════════════════╗")
    print("  ║     AION HAND SETUP WIZARD          ║")
    print("  ║     Let's get you configured!       ║")
    print("  ╚═════════════════════════════════════╝")
    print(f"{NC}")
    print(f"{DIM}  Press Enter to accept defaults shown in [brackets].{NC}")
    print(f"{DIM}  Press Ctrl+C at any time to quit.{NC}")


def step_choose_provider(config: dict[str, Any]) -> None:
    step("1/7: Choose AI Provider")
    names = {k: v["name"] for k, v in PROVIDERS.items()}
    current = config.get("AION_PROVIDER", "ollama")

    print(f"  {DIM}Select the AI provider to use with Aion Hand.{NC}")
    provider = prompt_choice("Provider", names, default=current)
    config["AION_PROVIDER"] = provider

    prov = PROVIDERS[provider]
    print()
    info(f"Selected: {prov['name']}")
    print(f"{DIM}    {prov['description']}{NC}")


def step_api_key(config: dict[str, Any]) -> None:
    step("2/7: API Key")
    provider = config.get("AION_PROVIDER", "ollama")
    prov = PROVIDERS[provider]

    if not prov["needs_key"]:
        ok(f"{prov['name']} does not require an API key.")
        # Clear any stale key
        config.pop("AION_API_KEY", None)
        return

    current = config.get("AION_API_KEY", "") or os.environ.get(
        f"{provider.upper()}_API_KEY", ""
    )
    if current:
        masked = current[:8] + "..." + current[-4:] if len(current) > 12 else "***"
        info(f"Current key: {masked}")
        if not prompt_yes_no("Change API key?", default=False):
            config["AION_API_KEY"] = current
            return

    print(f"  {DIM}{prov['install_hint']}{NC}")
    key = prompt(f"Enter {prov['name']} API key")
    while not key:
        print(f"  {RED}API key is required for {prov['name']}.{NC}")
        key = prompt(f"Enter {prov['name']} API key")
    config["AION_API_KEY"] = key
    ok("API key set.")


def step_model(config: dict[str, Any]) -> None:
    step("3/7: Default Model")
    provider = config.get("AION_PROVIDER", "ollama")
    prov = PROVIDERS[provider]
    current = config.get("AION_MODEL", prov["default_model"])

    print(f"  {DIM}Default model to use for conversations.{NC}")
    model = prompt("Model name", current)
    config["AION_MODEL"] = model
    ok(f"Model: {model}")


def step_features(config: dict[str, Any]) -> None:
    step("4/7: Features")

    features = [
        ("AION_ENABLE_MEMORY", "Persistent memory across sessions", True),
        ("AION_ENABLE_TOOLS", "Tool use (code execution, file ops, web)", True),
        ("AION_ENABLE_SKILLS", "Skill system (pluggable capabilities)", True),
        ("AION_ENABLE_BENCHMARKS", "Benchmarking & evaluation", False),
    ]

    print(f"  {DIM}Enable or disable Aion Hand features.{NC}")
    for key, desc, default in features:
        current_val = config.get(key)
        if current_val is None:
            use_default = default
        else:
            use_default = str(current_val).lower() in ("true", "1", "yes")

        enabled = prompt_yes_no(f"  Enable {desc}?", default=use_default)
        config[key] = str(enabled).lower()
        status = f"{GREEN}ON{NC}" if enabled else f"{RED}OFF{NC}"
        print(f"    {desc}: {status}")


def step_messaging(config: dict[str, Any]) -> None:
    step("5/7: Messaging (Optional)")

    if not prompt_yes_no("Configure messaging (Telegram, etc.)?", default=False):
        config.pop("AION_TELEGRAM_BOT_TOKEN", None)
        info("Messaging skipped — you can configure it later in .env")
        return

    token = prompt("Telegram bot token", "")
    if token:
        config["AION_TELEGRAM_BOT_TOKEN"] = token
        ok("Telegram configured.")


def step_test_connection(config: dict[str, Any]) -> None:
    step("6/7: Test Connection")
    provider = config.get("AION_PROVIDER", "ollama")

    print(f"  {DIM}Testing connection to {provider}...{NC}")

    try:
        if provider == "ollama":
            _test_ollama(config)
        elif provider == "openai":
            _test_openai(config)
        elif provider == "anthropic":
            _test_anthropic(config)
        elif provider == "google":
            _test_google(config)
        else:
            warn(f"No test for provider '{provider}'")
    except Exception as exc:
        warn(f"Connection test failed: {exc}")
        warn("You can fix this later by editing ~/.aion-hand/.env")


def _test_ollama(config: dict[str, Any]) -> None:
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        fail("Ollama CLI not found.")
        print(f"  {DIM}{PROVIDERS['ollama']['install_hint']}{NC}")
        return

    result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        fail("Ollama is not running.")
        print(f"  {DIM}Start it with: ollama serve{NC}")
        return

    model = config.get("AION_MODEL", "llama3.2")
    lines = result.stdout.strip().split("\n")
    models = [l.split()[0] for l in lines[1:] if l.strip()]

    if model not in models:
        warn(f"Model '{model}' not found locally.")
        if prompt_yes_no(f"Pull '{model}' now? (requires internet)", default=True):
            print(f"  {DIM}Pulling {model}...{NC}")
            pull = subprocess.run(["ollama", "pull", model], timeout=300)
            if pull.returncode == 0:
                ok(f"Model '{model}' pulled successfully.")
            else:
                fail(f"Failed to pull '{model}'.")
                return
    else:
        ok(f"Model '{model}' available.")

    # Quick generation test
    print(f"  {DIM}Testing generation...{NC}")
    test = subprocess.run(
        ["ollama", "run", "--nowordwrap", model, "Say OK"],
        capture_output=True, text=True, timeout=30,
    )
    if test.returncode == 0 and test.stdout.strip():
        ok(f"Generation works — got: {test.stdout.strip()[:60]}")
    else:
        warn("Generation test inconclusive.")


def _test_openai(config: dict[str, Any]) -> None:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.get("AION_API_KEY", ""))
        models = client.models.list()
        model_ids = [m.id for m in models.data[:5]]
        ok(f"Connected — available models: {', '.join(model_ids)}")
    except ImportError:
        warn("openai package not installed — install with: pip install openai")
    except Exception as exc:
        fail(f"Connection failed: {exc}")


def _test_anthropic(config: dict[str, Any]) -> None:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.get("AION_API_KEY", ""))
        # Lightweight call
        resp = client.messages.create(
            model=config.get("AION_MODEL", "claude-3-5-sonnet-20241022"),
            max_tokens=10,
            messages=[{"role": "user", "content": "Say OK"}],
        )
        ok(f"Connected — response: {resp.content[0].text.strip()[:40]}")
    except ImportError:
        warn("anthropic package not installed — install with: pip install anthropic")
    except Exception as exc:
        fail(f"Connection failed: {exc}")


def _test_google(config: dict[str, Any]) -> None:
    try:
        import google.generativeai as genai
        genai.configure(api_key=config.get("AION_API_KEY", ""))
        model = genai.GenerativeModel("gemini-1.5-flash")
        resp = model.generate_content("Say OK")
        ok(f"Connected — response: {resp.text.strip()[:40]}")
    except ImportError:
        warn("google-generativeai package not installed — install with: pip install google-generativeai")
    except Exception as exc:
        fail(f"Connection failed: {exc}")


def step_save(config: dict[str, Any]) -> None:
    step("7/7: Save Configuration")

    # Ensure directories exist
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Write .env
    env_lines = ["# Aion Hand Configuration", "# Generated by setup wizard", ""]
    env_key_order = [
        "AION_PROVIDER", "AION_API_KEY", "AION_MODEL",
        "AION_LOG_LEVEL", "AION_ENABLE_MEMORY", "AION_ENABLE_TOOLS",
        "AION_ENABLE_SKILLS", "AION_ENABLE_BENCHMARKS",
        "AION_TELEGRAM_BOT_TOKEN", "AION_DATA_DIR", "AION_MEMORY_DIR",
    ]
    for key in env_key_order:
        if key in config:
            env_lines.append(f"{key}={config[key]}")
    env_lines.append("")

    ENV_FILE.write_text("\n".join(env_lines))
    ok(f"Saved .env to {ENV_FILE}")

    # Write settings.json (non-secret settings for programmatic access)
    safe_config = {k: v for k, v in config.items() if "KEY" not in k and "SECRET" not in k and "TOKEN" not in k}
    safe_config["version"] = "0.1.0"
    CONFIG_FILE.write_text(json.dumps(safe_config, indent=2) + "\n")
    ok(f"Saved settings to {CONFIG_FILE}")


def print_done() -> None:
    print()
    print(f"{GREEN}{BOLD}")
    print("  ╔═════════════════════════════════════╗")
    print("  ║  ✅  Setup complete!                  ║")
    print("  ╚═════════════════════════════════════╝")
    print(f"{NC}")
    print(f"  {CYAN}{BOLD}Start Aion Hand:{NC}")
    print(f"    {BOLD}aion-hand{NC}")
    print()
    print(f"  {CYAN}{BOLD}Or with a specific model:{NC}")
    print(f"    {BOLD}aion-hand --model llama3.2{NC}")
    print()
    print(f"  {CYAN}{BOLD}Edit config anytime:{NC}")
    print(f"    {BOLD}nano ~/.aion-hand/.env{NC}")
    print(f"    {BOLD}aion-hand setup{NC}  (re-run wizard)")
    print()

# ── Existing config loader ────────────────────────────────────────────────

def load_existing_config() -> dict[str, Any]:
    """Load existing .env into a dict, if it exists."""
    config: dict[str, Any] = {}
    if not ENV_FILE.exists():
        return config

    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            config[key.strip()] = val.strip()
    return config


# ── Main ──────────────────────────────────────────────────────────────────

async def setup() -> None:
    """Run the interactive setup wizard."""
    config = load_existing_config()

    step_welcome()
    step_choose_provider(config)
    step_api_key(config)
    step_model(config)
    step_features(config)
    step_messaging(config)
    step_test_connection(config)
    step_save(config)
    print_done()


if __name__ == "__main__":
    asyncio.run(setup())
