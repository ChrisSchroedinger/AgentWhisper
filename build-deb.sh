#!/bin/sh
# Build dist/agentwhisper_<version>_all.deb with plain dpkg-deb.
# Python dependencies are NOT in the .deb; the postinst installs them
# into a private virtualenv (same pattern as the user-level install.sh).
set -e

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$REPO_DIR"

PKG=agentwhisper
VERSION=$(sed -n 's/^version = "\(.*\)"$/\1/p' pyproject.toml)
ARCH=all
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

echo "Building $PKG $VERSION ..."

# --- payload -----------------------------------------------------------
LIB="$STAGE/usr/lib/agentwhisper"
mkdir -p "$LIB" "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps" \
         "$STAGE/usr/share/doc/agentwhisper"

cp -r src pyproject.toml requirements.txt README.md "$LIB/"
cp packaging/setup-venv.sh "$LIB/"
chmod 755 "$LIB/setup-venv.sh"
find "$LIB" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

for name in agentwhisper agentwhisperd; do
    cat > "$STAGE/usr/bin/$name" <<EOF
#!/bin/sh
V=/usr/lib/agentwhisper/venv
[ -x "\$V/bin/$name" ] || { echo "$name: run 'sudo /usr/lib/agentwhisper/setup-venv.sh' first" >&2; exit 1; }
exec "\$V/bin/$name" "\$@"
EOF
    chmod 755 "$STAGE/usr/bin/$name"
done

sed "s|@BINDIR@|/usr/bin|" packaging/agentwhisper.desktop \
    > "$STAGE/usr/share/applications/agentwhisper.desktop"
cp src/agentwhisper/icons/agentwhisper.svg \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/agentwhisper.svg"
cp CHANGELOG.md LICENSE "$STAGE/usr/share/doc/agentwhisper/"

# --- control -----------------------------------------------------------
mkdir -p "$STAGE/DEBIAN"
INSTALLED_SIZE=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: Chris Schroedinger <259315013+ChrisSchroedinger@users.noreply.github.com>
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.11), python3-venv, python3-pip, python3-gi, python3-gi-cairo, gir1.2-ayatanaappindicator3-0.1, xclip, xdotool, libnotify-bin
Homepage: https://github.com/ChrisSchroedinger/agentwhisper
Description: Push-to-talk voice dictation using Whisper (X11)
 AgentWhisper is push-to-talk voice dictation for Linux/X11. Hold a
 hotkey (F12 by default) to record, release to transcribe locally with
 faster-whisper; the text is typed into the active window and copied to
 the clipboard. Local, offline, private.
 .
 Python dependencies are installed into a private virtualenv at package
 configure time (one-time ~200MB download).
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
case "$1" in
    configure)
        if ! /usr/lib/agentwhisper/setup-venv.sh; then
            echo "" >&2
            echo "WARNING: could not install Python dependencies (offline?)." >&2
            echo "AgentWhisper will not run until you execute:" >&2
            echo "  sudo /usr/lib/agentwhisper/setup-venv.sh" >&2
        fi
        command -v gtk-update-icon-cache >/dev/null 2>&1 && \
            gtk-update-icon-cache -q /usr/share/icons/hicolor 2>/dev/null || true
        command -v update-desktop-database >/dev/null 2>&1 && \
            update-desktop-database -q /usr/share/applications 2>/dev/null || true
        echo ""
        echo "AgentWhisper installed. Start it from the applications menu"
        echo "(Utility > AgentWhisper) or run: agentwhisperd"
        ;;
esac
exit 0
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

cat > "$STAGE/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
case "$1" in
    remove|upgrade)
        rm -rf /usr/lib/agentwhisper/venv
        ;;
esac
exit 0
EOF
chmod 755 "$STAGE/DEBIAN/prerm"

# --- build -------------------------------------------------------------
mkdir -p dist
if command -v fakeroot >/dev/null 2>&1; then
    fakeroot dpkg-deb --build "$STAGE" "dist/${PKG}_${VERSION}_${ARCH}.deb"
else
    dpkg-deb --build --root-owner-group "$STAGE" "dist/${PKG}_${VERSION}_${ARCH}.deb"
fi

echo ""
echo "Done: dist/${PKG}_${VERSION}_${ARCH}.deb"
echo "Install with: sudo apt install ./dist/${PKG}_${VERSION}_${ARCH}.deb"
