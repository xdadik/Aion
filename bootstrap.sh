#!/usr/bin/env bash
set -euo pipefail

# Aion Hand bootstrap installer.
# curl -fsSL https://raw.githubusercontent.com/xdadik/Aion/main/bootstrap.sh | bash

REPO_URL="https://github.com/xdadik/Aion.git"
INSTALL_DIR="${AION_HOME:-$HOME/.aion-hand}"
SRC_DIR="$INSTALL_DIR/src"
VENV_DIR="$INSTALL_DIR/venv"
BIN_DIR="$INSTALL_DIR/bin"

log(){ printf '\n[Aion] %s\n' "$*"; }
fatal(){ printf '\n[Aion] ERROR: %s\n' "$*" >&2; exit 1; }

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
    PYTHON="$candidate"; break
  fi
done
[ -n "$PYTHON" ] || fatal "Python 3.11+ is required."
command -v git >/dev/null 2>&1 || fatal "git is required."

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

if [ -f pyproject.toml ]; then
  SRC_DIR="$(pwd)"
elif [ -d "$SRC_DIR/.git" ]; then
  log "Updating Aion source"
  git -C "$SRC_DIR" pull --ff-only --quiet || fatal "Your local Aion checkout cannot be fast-forwarded. Resolve it and rerun."
else
  log "Downloading Aion Hand"
  git clone --depth 1 --branch main "$REPO_URL" "$SRC_DIR"
fi

log "Creating isolated environment"
"$PYTHON" -m venv "$VENV_DIR"
VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel >/dev/null

log "Installing Aion Hand"
"$VENV_PYTHON" -m pip install -e "$SRC_DIR[all]"

log "Verifying installation"
"$VENV_PYTHON" -c 'import aion_core; print("Aion Hand import OK")'

cat > "$BIN_DIR/aion-hand" <<EOF
#!/usr/bin/env bash
exec "$VENV_PYTHON" -m aion_hand_cli.cli "\$@"
EOF
chmod +x "$BIN_DIR/aion-hand"
ln -sf "$BIN_DIR/aion-hand" "$BIN_DIR/aion"

log "Installed successfully"
printf 'Run: %s/aion-hand --help\n' "$BIN_DIR"
printf 'Or add to PATH: export PATH="%s/bin:$PATH"\n' "$INSTALL_DIR"
