# Contributing to Aion Hand

Thanks for your interest in contributing! Aion Hand is a community-driven
project — every contribution matters.

## 🚀 Quick start for contributors

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/Aion.git
cd Aion

# 2. Add the upstream remote
git remote add upstream https://github.com/xdadik/Aion.git

# 3. Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate

# 4. Install in editable mode with dev dependencies
pip install -e ".[all,dev]"

# 5. Verify everything works
pytest --tb=short -q
aion-hand doctor

# 6. Create a feature branch
git checkout -b feat/my-awesome-feature
```

## 🧑‍💻 Ways to contribute

You don't have to write code to help! Here are ways to contribute:

### Code
- **Bug fixes** — see [issues labeled `bug`](https://github.com/xdadik/Aion/labels/bug)
- **New features** — see [issues labeled `enhancement`](https://github.com/xdadik/Aion/labels/enhancement)
- **New skills** — add a `SKILL.md` to `skills/library/`
- **New personas** — add a `SOUL.md` to `aion_core/persona/templates/`
- **New messaging adapters** — extend `aion_core/messaging/real_adapters/`
- **New tools** — extend `aion_core/tools/registry.py`

### Documentation
- Improve the README, ARCHITECTURE.md, COOKBOOK.md
- Write tutorials / blog posts
- Translate docs to other languages
- Improve docstrings

### Testing
- Write tests for untested code paths
- Add integration tests for messaging platforms
- Run the benchmark suite on different hardware

### Community
- Answer questions in [GitHub Discussions](https://github.com/xdadik/Aion/discussions)
- Triage issues
- Review pull requests
- Report bugs with clear repro steps

## 📋 Development workflow

### 1. Pick an issue

Browse [open issues](https://github.com/xdadik/Aion/issues) and comment on
the one you want to work on. We'll assign it to you so others don't duplicate
work.

No issue for what you want to do? Open one first.

### 2. Write code

Follow the existing style:
- `ruff check aion_core/ tests/` should pass (warnings OK, errors not)
- Type hints on all public functions
- Docstrings on all public classes and functions
- Lines ≤ 88 chars (black default)

### 3. Write tests

Every bug fix and new feature MUST include tests:

```python
# tests/test_my_feature.py
import pytest
from aion_core.my_module import my_function

class TestMyFeature:
    def test_basic_case(self):
        result = my_function("input")
        assert result == "expected"

    def test_edge_case(self):
        with pytest.raises(ValueError):
            my_function("")

    @pytest.mark.asyncio
    async def test_async_case(self):
        result = await my_function_async("input")
        assert result is not None
```

Run tests locally:
```bash
pytest tests/test_my_feature.py -v
pytest --tb=short -q  # full suite
```

### 4. Update docs

If your change is user-facing:
- Update `README.md`
- Update `CHANGELOG.md` under `[Unreleased]`
- Update `docs/INSTALL.md` if install steps changed
- Update `docs/examples/COOKBOOK.md` if new use case

### 5. Commit (Conventional Commits)

```bash
git add .
git commit -m "feat(memory): add vector similarity search

Adds a new MemoryManager.search_similar() method that uses cosine
similarity over embedded memory content. Falls back to FTS5 keyword
search when embeddings are unavailable.

Closes #123"
```

**Commit types:**
- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `style:` — formatting, lint, no code change
- `refactor:` — code restructure, no behavior change
- `test:` — adding tests
- `chore:` — tooling, deps, configs
- `perf:` — performance improvement

### 6. Push and open a PR

```bash
git push -u origin feat/my-awesome-feature
```

Then open a PR against `main`. The PR template will guide you.

### 7. Address review feedback

- Make changes as new commits (don't force-push during review)
- Reply to every comment (even with "👍")
- Mark conversations "resolved" once addressed

### 8. Squash-merge

Once approved, a maintainer will squash-merge your PR. The commit message
will be your PR title.

## 🏗️ Architecture overview

Before contributing, please read:
- [`ARCHITECTURE.md`](../ARCHITECTURE.md) — system overview
- [`docs/adr/`](../docs/adr/) — Architecture Decision Records
- [`CHANGELOG.md`](../CHANGELOG.md) — recent changes

Key principles:
- **Async throughout** — see ADR-0001
- **Zero hard dependencies** — core runs on Python stdlib
- **SKILL.md format** — see ADR-0002
- **SOUL.md format** — see ADR-0003
- **No circular imports** — `agent.core` may import subsystems; subsystems may not import `agent.loop`

## 🧪 Testing guidelines

### Unit tests
- One test class per public class
- Test the happy path AND edge cases (empty, null, very large, very small)
- Mock external dependencies (network, filesystem, time)
- Use `tmp_path` fixture for filesystem tests

### Integration tests
- Mark with `@pytest.mark.integration`
- Skip when env vars not set (e.g., `TG_BOT_TOKEN`)
- Don't actually call paid APIs in CI

### Async tests
- `pytest-asyncio` is configured with `asyncio_mode = "auto"`
- Just write `async def test_...` and it works

### Test naming
- `test_<thing>_<condition>` — e.g., `test_chat_returns_response_on_valid_input`
- `test_<thing>_raises_<error>_on_<condition>` — e.g., `test_connect_raises_on_invalid_token`

## 🎨 Code style

### Python
- Black formatting (line length 88)
- Type hints on all public functions
- Docstrings (Google style) on all public classes and functions
- No `print()` in library code — use `logging`
- No bare `except:` — catch specific exceptions

### Imports
```python
# Standard library
import asyncio
from pathlib import Path

# Third party
import pytest
from aiohttp import web

# Aion
from aion_core.agent.core import AionHand
```

### Naming
- `snake_case` for functions and variables
- `PascalCase` for classes
- `UPPER_SNAKE` for constants
- `_prefix` for private

## 📦 Releasing

Maintainers only:

1. Update `CHANGELOG.md` with the new version and date
2. Bump version in `pyproject.toml` and `aion_core/__init__.py`
3. Commit: `chore(release): v0.5.0`
4. Tag: `git tag v0.5.0 && git push origin v0.5.0`
5. The `release.yml` GitHub Action will build and publish automatically

## 🤝 Code of conduct

By participating, you agree to abide by the [Code of Conduct](./CODE_OF_CONDUCT.md).
Be kind. Be patient. Be excellent to each other.

## ❓ Questions?

- **Bug reports** → [GitHub Issues](https://github.com/xdadik/Aion/issues)
- **Questions / discussion** → [GitHub Discussions](https://github.com/xdadik/Aion/discussions)
- **Security reports** → see [SECURITY.md](./SECURITY.md) (don't open a public issue)
- **Real-time chat** → coming soon

## 🙏 Recognition

All contributors are listed in the [Contributors page](https://github.com/xdadik/Aion/graphs/contributors).
Significant contributions may be recognized with a mention in the README.

Thank you for making Aion Hand better! 💚
