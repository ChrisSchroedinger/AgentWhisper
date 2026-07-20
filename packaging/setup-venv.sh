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
    echo "Installing Python dependencies (one-time ~200MB download, takes a few minutes)..."
    # -q: no download/progress chatter; real errors still reach stderr.
    # --no-warn-conflicts: with system-site-packages, pip cross-checks
    # unrelated system apps (their deps never see this venv) and prints
    # scary but meaningless conflict errors. Our own set is consistent
    # (resolved from the project lockfile).
    # --no-deps: requirements.txt is a complete resolved lockfile, so
    # nothing is missing. It also keeps pip from pulling PyAV back in:
    # faster-whisper declares it, but only to decode audio files, which
    # AgentWhisper never does (it transcribes in-memory samples). The
    # lockfile excludes it, saving ~100MB of bundled FFmpeg on disk.
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q --no-warn-conflicts --no-deps \
        -r "$LIBDIR/requirements.txt"
    "$VENV/bin/pip" install -q --no-warn-conflicts --no-deps "$LIBDIR"
fi

echo "AgentWhisper virtualenv ready."
