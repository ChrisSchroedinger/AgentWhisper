#!/bin/sh
# AgentWhisper user-level installer: no sudo, no system files.
# Installs into ~/.local (bin wrappers, .desktop entry, icon) and
# creates the project virtualenv with uv. Idempotent; run again after
# pulling updates.
set -e

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "==> AgentWhisper installer (repo: $REPO_DIR)"

# --- uv ---------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is not installed. Install it with:" >&2
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "then re-run this script." >&2
    exit 1
fi

# --- virtualenv -------------------------------------------------------
# Two hard requirements, both for the tray icon's GTK bindings
# (python3-gi), which pip cannot install:
#   1. the venv must be based on the SYSTEM Python (/usr/bin/python3),
#      not a uv-managed standalone build — Debian's gi is compiled for
#      the system interpreter and lives in its dist-packages;
#   2. the venv must include system site-packages to see it.
cd "$REPO_DIR"
SYS_PY=$(command -v python3)

venv_ok() {
    [ -x .venv/bin/python3 ] || return 1
    grep -qx 'include-system-site-packages = true' .venv/pyvenv.cfg || return 1
    grep -qx "home = $(dirname "$SYS_PY")" .venv/pyvenv.cfg || return 1
}

if ! venv_ok; then
    echo "==> Creating virtualenv from system Python ($SYS_PY, system site-packages)"
    rm -rf .venv
    uv venv --python "$SYS_PY" --system-site-packages
fi
echo "==> Installing Python dependencies"
uv sync

# --- tray prerequisites (warn, don't fail: daemon runs headless too) ---
if ! .venv/bin/python3 -c "import gi" 2>/dev/null; then
    echo ""
    if "$SYS_PY" -c "import gi" 2>/dev/null; then
        echo "WARNING: the venv cannot see python3-gi although the system Python can." >&2
        echo "This should not happen — please report it. Venv base:" >&2
        grep '^home' .venv/pyvenv.cfg >&2
    else
        echo "WARNING: python3-gi is not available — the tray icon will not show." >&2
        echo "Fix with:  sudo apt install python3-gi python3-gi-cairo gir1.2-ayatanaappindicator3-0.1" >&2
        echo "then re-run this script." >&2
    fi
    echo ""
fi

# --- desktop tools (warn, don't fail) ----------------------------------
MISSING=""
for tool in xclip xdotool notify-send; do
    command -v "$tool" >/dev/null 2>&1 || MISSING="$MISSING $tool"
done
if [ -n "$MISSING" ]; then
    echo ""
    echo "WARNING: missing desktop tools:$MISSING" >&2
    echo "Typing/clipboard/notifications need them. Fix with:" >&2
    echo "  sudo apt install xclip xdotool libnotify-bin" >&2
    echo ""
fi

# --- launchers --------------------------------------------------------
mkdir -p "$BIN_DIR"
for name in agentwhisper agentwhisperd; do
    cat > "$BIN_DIR/$name" <<EOF
#!/bin/sh
exec "$REPO_DIR/.venv/bin/$name" "\$@"
EOF
    chmod +x "$BIN_DIR/$name"
done
echo "==> Launchers: $BIN_DIR/agentwhisper, $BIN_DIR/agentwhisperd"

# --- icon + menu entry ------------------------------------------------
mkdir -p "$ICON_DIR" "$APPS_DIR"
cp "$REPO_DIR/src/agentwhisper/icons/agentwhisper.svg" "$ICON_DIR/agentwhisper.svg"
sed "s|@BINDIR@|$BIN_DIR|" "$REPO_DIR/packaging/agentwhisper.desktop" \
    > "$APPS_DIR/agentwhisper.desktop"
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database -q "$APPS_DIR" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "==> Menu entry + icon installed"

echo ""
echo "Done. Start AgentWhisper from the XFCE menu (Utility > AgentWhisper)"
echo "or run: agentwhisperd"
echo "Check:  agentwhisper status"
