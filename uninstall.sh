#!/bin/sh
# AgentWhisper uninstaller: removes everything install.sh created.
# Keeps your config and logs unless you pass --purge.
set -e

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

echo "==> Uninstalling AgentWhisper"

# Stop a running daemon (best effort).
if [ -x "$REPO_DIR/.venv/bin/agentwhisper" ]; then
    "$REPO_DIR/.venv/bin/agentwhisper" quit 2>/dev/null || true
    sleep 1
fi
pkill -f "agentwhisper/.venv/bin/agentwhisperd" 2>/dev/null || true
rm -f "${XDG_RUNTIME_DIR:-/tmp}/agentwhisper.sock" "/tmp/agentwhisper-$(id -u).sock"

# Launchers, menu entry, icon.
rm -f "$BIN_DIR/agentwhisper" "$BIN_DIR/agentwhisperd"
rm -f "$APPS_DIR/agentwhisper.desktop"
rm -f "$ICON_DIR/agentwhisper.svg"
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database -q "$APPS_DIR" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

# Virtualenv (machine-local; the repo itself is untouched).
rm -rf "$REPO_DIR/.venv"

if [ "$1" = "--purge" ]; then
    rm -rf "$HOME/.config/agentwhisper" "$HOME/.local/state/agentwhisper"
    echo "==> Removed config and logs (--purge)"
else
    echo "==> Kept config (~/.config/agentwhisper) and logs"
    echo "    (~/.local/state/agentwhisper); remove them with: $0 --purge"
fi

echo "Done. Reinstall any time with: $REPO_DIR/install.sh"
