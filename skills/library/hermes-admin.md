<!-- Ported from Hermes Agent skill collection. Original author: Hermes / Nous Research. -->
<!-- Licensed under the same terms as the original (MIT). -->

---
name: hermes-admin
description: "Hermes lifecycle management: backup, restore, server migration, config portability."
version: 1.0.0
author: Aria (agent-created)
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [backup, restore, migration, devops, administration]
---

# Hermes Administration

Managing Hermes state across server restarts, migrations, and fresh installs.

## What Persists Where

| Data | Location | Survives restart? |
|------|----------|-------------------|
| Config | `~/.hermes/config.yaml` | Yes (on disk) |
| Skills | `~/.hermes/skills/` | Yes (on disk) |
| Memory | `~/.hermes/.env` | Yes (on disk) |
| Auth tokens | `~/.hermes/auth.json` | Yes (on disk) |
| Sessions | `~/.hermes/state.db` | Yes (on disk) |

All data lives at `~/.hermes/`. If the server is wiped, everything is gone unless backed up.

## Backup to GitHub

Scripts at `~/.hermes/scripts/`:
- `backup.sh` — tarballs state and pushes to private GitHub repo
- `restore.sh` — pulls from GitHub and restores state

Setup:
1. User connects GitHub (see github-auth skill)
2. Run `bash ~/.hermes/scripts/backup.sh` for first backup
3. Cron job `aria-backup` runs every 6 hours automatically

Backup repo: private repo at `github.com/<username>/hermes-backup`

## Restore on New Server

```bash
# On fresh server:
git clone https://github.com/<username>/hermes-backup.git /tmp/hermes-backup
bash /tmp/hermes-backup/restore.sh
# Restart Hermes
```

## Local Service Deployment

See `references/searxng-setup.md` for a complete SearXNG installation recipe (bare metal, no Docker) with pitfall notes on the `--no-build-isolation` build fix.

## Disk Cleanup on Constrained Servers

On small instances (6-8GB disk), Hermes + dependencies can fill the disk fast. Safe-to-remove items for CLI/gateway-only installs:

| Path | Size | Safe to remove? | Why |
|------|------|-----------------|-----|
| `~/.hermes/hermes-agent/node_modules/electron` | ~290MB | Yes (CLI only) | Desktop app runtime |
| `~/.hermes/hermes-agent/node_modules/@tauri-apps` | ~37MB | Yes | Desktop framework |
| `~/.hermes/hermes-agent/node_modules/electron-winstaller` | ~31MB | Yes | Desktop installer |
| `~/.hermes/hermes-agent/apps/desktop` | ~58MB | Yes | Desktop app source |
| `~/.hermes/hermes-agent/apps/bootstrap-installer` | ~4MB | Yes | Installer scripts |
| `~/.hermes/hermes-agent/node_modules/@tabler` | ~141MB | Yes | Desktop UI icons |
| `~/.hermes/hermes-agent/node_modules/@icons-pack` | ~60MB | Yes | Icon packs |
| `~/.hermes/hermes-agent/node_modules/lucide-react` | ~46MB | Yes | Icons |
| `~/.hermes/hermes-agent/node_modules/three` | ~33MB | Yes | 3D library (desktop) |
| `~/.hermes/hermes-agent/node_modules/mermaid` | ~84MB | Yes | Diagrams (desktop) |
| `~/.hermes/hermes-agent/node_modules/agent-browser` | ~69MB | Yes | Browser tools |
| `~/.hermes/hermes-agent/node_modules/@rolldown` | ~39MB | Yes | Bundler |
| `~/.hermes/hermes-agent/node_modules/typescript` | ~24MB | Yes | Not needed at runtime |
| `~/.hermes/hermes-agent/tests` | ~36MB | Yes | Test files |
| `~/.hermes/hermes-agent/website` | ~27MB | Yes | Docs site source |
| `~/.hermes/hermes-agent/infographic` | ~14MB | Yes | Templates |
| `~/.hermes/hermes-agent/optional-skills` | ~9MB | Yes | Uninstalled skills |
| `~/.hermes/hermes-agent/web` | ~10MB | Yes | Web frontend |
| `~/.hermes/hermes-agent/.git` | ~72MB | Yes if backed up | Git history |
| `~/.cache/node-gyp` | ~65MB | Yes | Build cache |
| `~/.cache/pip` | varies | Yes | Pip cache |
| `~/.npm` | ~200MB+ | Yes | NPM cache |

Typical savings: ~1.3GB on a CLI/gateway-only install.

Pitfall: Do NOT remove `node_modules/node-pty` (~63MB) — needed for terminal tools. Do NOT remove `agent-browser` if browser tools are enabled.

## Python Package Cleanup (venv)

On constrained servers, the hermes venv can be trimmed. These packages are safe to remove if not actively used:

| Package | Size | Safe to remove? | Why |
|---------|------|-----------------|-----|
| `scipy` + `scipy-libs` | ~60MB | Yes | Scientific computing, not used by hermes core |
| `pandas` | ~10MB | Yes | Data analysis, not used by hermes core |
| `scikit-learn` | ~30MB | Yes | ML, not used by hermes core |
| `ctranslate2` + `ctranslate2-libs` | ~135MB | Yes | ML inference, was for faster-whisper |
| `av` + `av-libs` | ~102MB | Yes | Video processing, not used by hermes core |
| `onnxruntime` | ~52MB | Yes | ML inference, not used by hermes core |
| `reportlab` | ~5MB | Yes | PDF generation, not used by hermes core |
| `pyvis` | ~4MB | Yes | Network visualization, not used by hermes core |
| `uvloop` | ~15MB | Yes | Async speedup, not critical |
| `ipython` + deps | ~10MB | Yes | Interactive shell, not needed at runtime |
| `fire` | ~2MB | Yes | CLI framework, not used by hermes core |
| `tornado` | ~2MB | Yes | Async framework, not used by hermes core |
| `psutil` | ~1MB | Yes | System monitor, not used by hermes core |

Command to remove:
```bash
~/.hermes/hermes-agent/venv/bin/pip uninstall -y scipy scipy-libs pandas scikit-learn ctranslate2 ctranslate2-libs av av-libs onnxruntime reportlab pyvis uvloop ipython fire tornado psutil
```

Verify after removal:
```bash
~/.hermes/hermes-agent/venv/bin/python -c "import fastapi; import pydantic; import httpx; import aiohttp; print('Core OK')"
```

Pitfall: Do NOT remove `annotated-doc` — required by fastapi. Do NOT remove `curl-cffi` — required by maigret (OSINT tool).

## Tool Installation Pitfalls

When evaluating tools to install on constrained servers, check before cloning:

| Tool | Issue | Verdict |
|------|-------|---------|
| agenticSeek | Requires Python <3.13, we have 3.14 | Skip |
| pentagi | Docker-based, not a pip package | Skip (no Docker) |
| context7 | Node.js only | Skip (no npm) |
| ponytail | Claude skill, not pip | Skip |
| gitleaks | Go binary, no pre-built Linux | Skip |
| cognee | Pulls 761MB of dependencies (lancedb, pyarrow, litellm) | Skip on small disks |
| n8n | ~500MB+, redundant with hermes | Skip |

Pattern: before `git clone` + `pip install -e .`, check:
1. `cat pyproject.toml | head -20` — check Python version requirement
2. `cat requirements.txt` — check dependency count/size
3. `grep -i docker Dockerfile` — check if Docker-based
4. `ls package.json go.mod Cargo.toml` — check if non-Python

## Currently Installed Tools (pip)

After cleanup and new installs, these are in the hermes venv:

| Tool | Command | Purpose |
|------|---------|---------|
| theHarvester | `~/.hermes/hermes-agent/venv/bin/theHarvester -d <domain>` | Email/subdomain/IP DNS enumeration |
| mem0 | `import mem0` | Smart memory extraction, deduplication |
| firecrawl | `import firecrawl` | Web scraping with anti-bot bypass |
| graphify | `import graphify` | Codebase → knowledge graph |
| headroom | `import headroom` | Compress tool outputs (60-95% token savings) |
| meilisearch | `~/.hermes/bin/meilisearch` | Fast hybrid search engine (binary) |

## Installed Tools (non-pip)

| Tool | Location | Purpose |
|------|----------|---------|
| meilisearch | `~/.hermes/bin/meilisearch` | Fast search engine (Go binary) |

## Key Commands

```bash
hermes config edit          # edit config
hermes skills list          # see installed skills
hermes memory status        # check memory state
hermes auth list            # list credential pools
hermes doctor               # health check
df -h /                     # check disk usage
du -sh ~/.hermes/*          # find large Hermes dirs
```
