#!/bin/sh
# Create or repair the AgentWhisper virtualenv for the .deb install.
# Idempotent; run as root from the package postinst on every configure.
set -e

LIBDIR=/usr/lib/agentwhisper
VENV="$LIBDIR/venv"

# The venv must be based on the system Python WITH system site-packages:
# the tray icon needs Debian's python3-gi/AppIndicator bindings, which
# pip cannot install.
if [ ! -x "$VENV/bin/python3" ]; then
    echo "Creating virtualenv at $VENV ..."
    python3 -m venv --system-site-packages "$VENV"
elif grep -qx 'include-system-site-packages = false' "$VENV/pyvenv.cfg" 2>/dev/null; then
    sed -i 's/^include-system-site-packages = false$/include-system-site-packages = true/' \
        "$VENV/pyvenv.cfg"
fi

if ! "$VENV/bin/python3" -c "import agentwhisper, faster_whisper, sounddevice, Xlib" \
        2>/dev/null; then
    echo "Installing Python dependencies (downloads ~200MB, one time)..."
    "$VENV/bin/pip" install --upgrade pip >/dev/null
    "$VENV/bin/pip" install -r "$LIBDIR/requirements.txt"
    "$VENV/bin/pip" install --no-deps "$LIBDIR"
fi

echo "AgentWhisper virtualenv ready."
