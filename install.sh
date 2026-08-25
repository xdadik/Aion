#!/usr/bin/env bash
# ==============================================================================
# Aion Hand Installer
# The easiest way to install Aion Hand — just like Hermes.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/xdadik/Aion/main/install.sh | bash
#
# Or locally:
#   bash install.sh
# ==============================================================================
set -euo pipefail

AION_HAND_VERSION="0.4.0"
INSTALL_DIR="${HOME}/.aion-hand"
BIN_DIR="${INSTALL_DIR}/bin"
VENV_DIR="${INSTALL_DIR}/venv"
REPO_URL="https://github.com/xdadik/Aion"
BRANCH="main"

# ── Colors ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info()    { echo -e "${BLUE}  [INFO]${NC} $*"; }
success() { echo -e "${GREEN}  [OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}  [WARN]${NC} $*"; }
error()   { echo -e "${RED}  [ERR]${NC}  $*"; }
step()    { echo -e "${PURPLE}${BOLD}  ── $* ──${NC}"; }

# ── Cleanup on exit ─────────────────────────────────────────────
cleanup() {
    if [ -n "${VIRTUAL_ENV:-}" ]; then
        deactivate 2>/dev/null || true
    fi
}
trap cleanup EXIT

# ── Banner ────────────────────────────────────────────────────────
print_banner() {
    echo -e "${PURPLE}"
    echo '     ╔══════════════════════════════════╕'
    echo '     ║        🤖  AION HAND  🤖               ║'
    echo '     ║     The AI Operating System             ║'
    echo "     ║            v${AION_HAND_VERSION}                       ║"
    echo '     ╚══════════════════════════════════╝'
    echo -e "${NC}"
    echo -e "${DIM}  Installing to: ${INSTALL_DIR}${NC}"
    echo ""
}

# ── Parse arguments ──────────────────────────────────────────────
parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --prefix|--dir)
                INSTALL_DIR="$2"
                BIN_DIR="${INSTALL_DIR}/bin"
                VENV_DIR="${INSTALL_DIR}/venv"
                shift 2
                ;;
            --version)
                echo "aion-hand ${AION_HAND_VERSION}"
                exit 0
                ;;
            --help|-h)
                echo "Aion Hand Installer v${AION_HAND_VERSION}"
                echo ""
                echo "Usage: install.sh [OPTIONS]"
                echo ""
                echo "Options:"
                echo "  --dir DIR     Installation directory (default: ~/.aion-hand)"
                echo "  --version     Print version and exit"
                echo "  --help        Show this help"
                echo "  --uninstall   Remove Aion Hand installation"
                exit 0
                ;;
            --uninstall)
                do_uninstall
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                echo "  Run with --help for usage."
                exit 1
                ;;
        esac
    done
}

# ── Uninstall ──────────────────────────────────────────────────
do_uninstall() {
    if [ ! -d "${INSTALL_DIR}" ]; then
        warn "Aion Hand not found at ${INSTALL_DIR}"
        exit 0
    fi
    echo -e "${YELLOW}  Uninstalling Aion Hand from ${INSTALL_DIR}...${NC}"
    rm -rf "${INSTALL_DIR}"
    for rc in "${HOME}/.bashrc" "${HOME}/.zshrc" "${HOME}/.profile"; do
        if [ -f "$rc" ]; then
            sed -i '/# Aion Hand/,+2d' "$rc" 2>/dev/null || true
        fi
    done
    echo -e "${GREEN}  Uninstalled. Open a new shell or run: source ~/.bashrc${NC}"
}

# ── Check system requirements ──────────────────────────────────────
check_requirements() {
    step "Checking system requirements"
    local has_error=0

    # --- OS ---
    local os_name="Unknown"
    if [[ "${OSTYPE:-}" == linux* ]]; then
        os_name="Linux ($(uname -m))"
    elif [[ "${OSTYPE:-}" == darwin* ]]; then
        os_name="macOS ($(uname -m))"
    elif [[ "${OSTYPE:-}" == msys* ]] || [[ "${OSTYPE:-}" == cygwin* ]]; then
        error "Windows detected. Please use install.ps1 instead."
        echo "  irm https://raw.githubusercontent.com/xdadik/Aion/main/install.ps1 | iex"
        exit 1
    fi
    info "OS: ${os_name}"

    # --- Python ---
    if command -v python3 &>/dev/null; then
        local py_ver
        py_ver=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
        local py_major py_minor
        py_major=$(python3 -c 'import sys; print(sys.version_info.major)')
        py_minor=$(python3 -c 'import sys; print(sys.version_info.minor)')
        if (( py_major >= 3 && py_minor >= 11 )); then
            success "Python ${py_ver}"
        else
            error "Python 3.11+ required (found ${py_ver})"
            echo -e "${DIM}  Install: https://www.python.org/downloads/  or  sudo apt install python3.11${NC}"
            has_error=1
        fi
    else
        error "python3 not found"
        echo -e "${DIM}  Install: https://www.python.org/downloads/  or  sudo apt install python3.11${NC}"
        has_error=1
    fi

    # --- pip ---
    if command -v pip3 &>/dev/null; then
        success "pip3 available"
    elif python3 -m pip --version &>/dev/null; then
        success "pip (via python3 -m pip)"
    else
        warn "pip not found — will bootstrap with ensurepip"
    fi

    # --- git ---
    if command -v git &>/dev/null; then
        success "git $(git --version | awk '{print $3}')"
    else
        warn "git not found — auto-update will be unavailable"
    fi

    # --- bc (for version compare) ---
    if ! command -v bc &>/dev/null; then
        warn "bc not found — using integer version comparison"
    fi

    if (( has_error )); then
        echo ""
        error "Missing required dependencies. Please fix the above and retry."
        exit 1
    fi
    echo ""
}

# ── Create directories ──────────────────────────────────────────
create_directories() {
    step "Creating installation directories"
    mkdir -p "${BIN_DIR}"
    mkdir -p "${INSTALL_DIR}/data"
    mkdir -p "${INSTALL_DIR}/memory"
    mkdir -p "${INSTALL_DIR}/skills"
    mkdir -p "${INSTALL_DIR}/tools"
    mkdir -p "${INSTALL_DIR}/logs"
    mkdir -p "${INSTALL_DIR}/knowledge"
    mkdir -p "${INSTALL_DIR}/benchmarks"
    mkdir -p "${INSTALL_DIR}/config"
    mkdir -p "${INSTALL_DIR}/platforms"
    mkdir -p "${INSTALL_DIR}/plugins"
    mkdir -p "${INSTALL_DIR}/providers"
    mkdir -p "${INSTALL_DIR}/profiles"
    success "Directories created at ${INSTALL_DIR}"
    echo ""
}

# ── Create virtual environment ────────────────────────────────────
create_venv() {
    step "Creating Python virtual environment"

    if [ -d "${VENV_DIR}" ]; then
        warn "Existing venv found — removing for fresh install"
        rm -rf "${VENV_DIR}"
    fi

    # Try creating venv without pip first (faster), fall back to with pip
    if ! python3 -m venv "${VENV_DIR}" --without-pip 2>/dev/null; then
        python3 -m venv "${VENV_DIR}"
    fi

    # Activate
    # shellcheck source=/dev/null
    source "${VENV_DIR}/bin/activate"

    # Bootstrap pip if missing
    if ! command -v pip &>/dev/null; then
        python3 -m ensurepip --upgrade 2>/dev/null || {
            curl -fsSL https://bootstrap.pypa.io/get-pip.py | python3 -
        }
    fi

    # Upgrade pip & install wheel for faster builds
    pip install --quiet --upgrade pip wheel 2>&1 | tail -1
    success "Virtual environment ready at ${VENV_DIR}"
    echo ""
}

# ── Clone or update repository ──────────────────────────────────
fetch_source() {
    step "Fetching Aion Hand source"
    local src_dir="${INSTALL_DIR}/src"

    if command -v git &>/dev/null; then
        if [ -d "${src_dir}/.git" ]; then
            info "Updating existing clone..."
            git -C "${src_dir}" pull --ff-only --quiet 2>/dev/null || {
                warn "Git pull failed — using existing source"
            }
        else
            info "Cloning from ${REPO_URL}..."
            git clone --depth 1 --branch "${BRANCH}" "${REPO_URL}" "${src_dir}" 2>/dev/null || {
                warn "Git clone failed — will try PyPI install"
                src_dir=""
            }
        fi
    else
        src_dir=""
    fi

    # Store path for later use
    AION_SRC_DIR="${src_dir}"
}

# ── Install Aion Hand ────────────────────────────────────────
install_aion_hand() {
    step "Installing Aion Hand v${AION_HAND_VERSION}"
    local installed=0

    # Strategy 1: Install from local clone
    if [ -n "${AION_SRC_DIR:-}" ] && [ -f "${AION_SRC_DIR}/pyproject.toml" ]; then
        info "Installing from source clone..."
        pip install --quiet -e "${AION_SRC_DIR}[all]" 2>&1 && installed=1
    fi

    # Strategy 2: Install from current directory (local dev install)
    if (( ! installed )) && [ -f "pyproject.toml" ]; then
        info "Installing from current directory..."
        pip install --quiet -e ".[all]" 2>&1 && installed=1
    fi

    # Strategy 3: Install from setup.py
    if (( ! installed )) && [ -f "setup.py" ]; then
        info "Installing from setup.py..."
        pip install --quiet -e "." 2>&1 && installed=1
    fi

    # Strategy 4: Install from PyPI
    if (( ! installed )); then
        info "Installing from PyPI..."
        if pip install --quiet aion-hand 2>/dev/null; then
            installed=1
        else
            error "Could not install aion-hand from any source"
            echo -e "${DIM}  Tried: local clone → current dir → PyPI${NC}"
            echo -e "${DIM}  Make sure you're in the aion-hand repo, or the package is on PyPI.${NC}"
            exit 1
        fi
    fi

    success "Aion Hand v${AION_HAND_VERSION} installed"
    echo ""
}

# ── Create CLI wrapper ────────────────────────────────────────
create_cli_wrapper() {
    step "Creating CLI commands"

    # Main command
    cat > "${BIN_DIR}/aion-hand" << 'WRAPPER'
#!/usr/bin/env bash
# Aion Hand CLI wrapper — installed by install.sh
set -euo pipefail

AION_HOME="${HOME}/.aion-hand"
VENV_DIR="${AION_HOME}/venv"

if [ ! -d "${VENV_DIR}" ]; then
    echo "[ERROR] Aion Hand virtual environment not found."
    echo "  Run: curl -fsSL https://raw.githubusercontent.com/xdadik/Aion/main/install.sh | bash"
    exit 1
fi

source "${VENV_DIR}/bin/activate"

# Pass all arguments to the CLI module
if python3 -m aion_hand_cli.cli "$@" 2>/dev/null; then
    exit 0
elif python3 -m aion_core "$@" 2>/dev/null; then
    exit 0
else
    echo "Could not find Aion Hand CLI module."
    echo "  Try: aion-hand setup"
    exit 1
fi
WRAPPER
    chmod +x "${BIN_DIR}/aion-hand"

    # Convenience alias: 'aion'
    cat > "${BIN_DIR}/aion" << 'WRAPPER'
#!/usr/bin/env bash
exec "${HOME}/.aion-hand/bin/aion-hand" "$@"
WRAPPER
    chmod +x "${BIN_DIR}/aion"

    success "Commands: aion-hand, aion"
    echo ""
}

# ── Configure shell ──────────────────────────────────────────
setup_shell() {
    step "Configuring shell integration"

    local rc_files=()
    local detected_shell=""

    # Detect current shell
    if [ -n "${ZSH_VERSION:-}" ]; then
        detected_shell="zsh"
    elif [ -n "${BASH_VERSION:-}" ]; then
        detected_shell="bash"
    fi

    case "${detected_shell}" in
        zsh)
            rc_files=("${HOME}/.zshrc")
            ;;
        bash)
            rc_files=("${HOME}/.bashrc")
            if [[ "${OSTYPE:-}" == linux* ]]; then
                rc_files+=("${HOME}/.profile")
            fi
            ;;
        *)
            [ -f "${HOME}/.bashrc" ]  && rc_files+=("${HOME}/.bashrc")
            [ -f "${HOME}/.zshrc" ]  && rc_files+=("${HOME}/.zshrc")
            [ -f "${HOME}/.profile" ] && rc_files+=("${HOME}/.profile")
            ;;
    esac

    local modified=0
    for rc in "${rc_files[@]}"; do
        [ -f "$rc" ] || continue
        if ! grep -q 'AION_HAND_HOME' "$rc" 2>/dev/null; then
            {
                echo ''
                echo '# Aion Hand'
                echo 'export AION_HAND_HOME="${HOME}/.aion-hand"'
                echo 'export PATH="${AION_HAND_HOME}/bin:$PATH"'
            } >> "$rc"
            success "Added to ${rc}"
            modified=1
        else
            info "Already configured in ${rc}"
        fi
    done

    if (( modified )); then
        echo -e "${DIM}  Run 'source ~/.bashrc' (or open a new terminal) to use aion-hand.${NC}"
    fi
    echo ""
}

# ── Setup environment file ─────────────────────────────────────
default_env() {
    cat << 'ENVFILE'
# Aion Hand Configuration
# =======================

# AI Provider: openai | anthropic | ollama
AION_PROVIDER=ollama

# API Key (not needed for Ollama)
# AION_API_KEY=sk-...

# Default model
AION_MODEL=

# Logging level: DEBUG | INFO | WARNING | ERROR
AION_LOG_LEVEL=INFO

# Data directory
AION_DATA_DIR=~/.aion-hand/data

# Memory directory
AION_MEMORY_DIR=~/.aion-hand/memory

# Security
AION_SECURITY_REDACT=true
AION_SECURITY_YOLO=false

# Context limits
AION_MAX_TOKENS=4096
AION_CONTEXT_COMPRESSION=80

# Gateway
AION_GATEWAY_PLATFORMS=
AION_MCP_SERVERS=
ENVFILE
}

setup_env() {
    step "Setting up configuration"

    local env_file="${INSTALL_DIR}/.env"
    local example_found=""

    for candidate in \
        ".env.example" \
        "${AION_SRC_DIR:-}/.env.example" \
        "${INSTALL_DIR}/src/.env.example"; do
        if [ -f "${candidate}" ]; then
            example_found="${candidate}"
            break
        fi
    done

    if [ -n "${example_found}" ] && [ ! -f "${env_file}" ]; then
        cp "${example_found}" "${env_file}"
        success ".env template created at ${env_file}"
        echo -e "${DIM}  Edit this file to add your API keys.${NC}"
    elif [ -f "${env_file}" ]; then
        info "Existing .env preserved"
    else
        default_env > "${env_file}"
        success "Default .env created at ${env_file}"
    fi
    echo ""
}

# ── Write version file ─────────────────────────────────────────
write_version() {
    cat > "${INSTALL_DIR}/VERSION" << EOF
${AION_HAND_VERSION}
$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
}

# ── Print success ──────────────────────────────────────────
print_success() {
    echo ""
    echo -e "${GREEN}╔═════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ✅  Aion Hand installed successfully!   ║${NC}"
    echo -e "${GREEN}══════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║                                           ║${NC}"
    echo -e "${GREEN}║  ${CYAN}1. Reload shell:${NC}                         ${GREEN}║${NC}"
    echo -e "${GREEN}║     ${BOLD}source ~/.bashrc${NC}  (or open a new terminal) ${GREEN}║${NC}"
    echo -e "${GREEN}║                                           ║${NC}"
    echo -e "${GREEN}║  ${CYAN}2. Configure:${NC}                           ${GREEN}║${NC}"
    echo -e "${GREEN}║     ${BOLD}aion-hand setup${NC}                       ${GREEN}║${NC}"
    echo -e "${GREEN}║                                           ║${NC}"
    echo -e "${GREEN}║  ${CYAN}3. Start using:${NC}                         ${GREEN}║${NC}"
    echo -e "${GREEN}║     ${BOLD}aion-hand${NC}                             ${GREEN}║${NC}"
    echo -e "${GREEN}║                                           ║${NC}"
    echo -e "${GREEN}╠═════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║  ${DIM}Config:  ${YELLOW}~/.aion-hand/.env${NC}             ${GREEN}║${NC}"
    echo -e "${GREEN}║  ${DIM}Logs:    ${YELLOW}~/.aion-hand/logs/${NC}             ${GREEN}║${NC}"
    echo -e "${GREEN}║  ${DIM}Data:    ${YELLOW}~/.aion-hand/data/${NC}             ${GREEN}║${NC}"
    echo -e "${GREEN}║  ${DIM}Version: ${YELLOW}${AION_HAND_VERSION}${NC}                             ${GREEN}║${NC}"
    echo -e "${GREEN}╚═════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${DIM}  📖 Docs:  ${REPO_URL}#readme${NC}"
    echo -e "${DIM}  🐛 Issues: ${REPO_URL}/issues${NC}"
    echo -e "${DIM}  💬 Discord: https://discord.gg/aion-hand${NC}"
    echo ""
}

# ── Main ────────────────────────────────────────────────────
main() {
    parse_args "$@"
    print_banner
    check_requirements
    create_directories
    create_venv
    fetch_source
    install_aion_hand
    create_cli_wrapper
    setup_shell
    setup_env
    write_version
    print_success
}

main "$@"