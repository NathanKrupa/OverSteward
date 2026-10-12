#!/usr/bin/env bash
# ABOUTME: Install the pinned Linux restic binary into ~/.local/bin, verified by sha256 — no sudo.
# ABOUTME: Idempotent: exits 0 without downloading when the pinned version is already installed.
#
# Usage: ops/wsl/install-restic.sh
#
# The version and checksum are pinned here, never read from the network: the
# checksum is the one restic publishes in SHA256SUMS for the release, copied
# into this file when the pin was chosen. Bumping restic is an edit to both
# lines, reviewed like any other change.
#
# Overrides (for tests): RESTIC_INSTALL_DIR (default ~/.local/bin) and
# RESTIC_DOWNLOAD_URL (default the GitHub release asset).
#
# Exit codes: 0 installed or already current; 1 download, checksum or install
# failed (nothing is installed on a checksum mismatch).
set -euo pipefail

RESTIC_VERSION="0.19.1"
RESTIC_SHA256="f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c"
ASSET="restic_${RESTIC_VERSION}_linux_amd64.bz2"

install_dir="${RESTIC_INSTALL_DIR:-$HOME/.local/bin}"
url="${RESTIC_DOWNLOAD_URL:-https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/${ASSET}}"
target="$install_dir/restic"

if [ -x "$target" ] && "$target" version 2>/dev/null | grep -q "^restic ${RESTIC_VERSION} "; then
    echo "restic ${RESTIC_VERSION} already installed at $target"
    exit 0
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if ! curl -fsSL -o "$work/$ASSET" "$url"; then
    echo "FAILED - could not download $url" >&2
    exit 1
fi

actual="$(sha256sum "$work/$ASSET" | cut -d' ' -f1)"
if [ "$actual" != "$RESTIC_SHA256" ]; then
    echo "FAILED - sha256 mismatch for $ASSET: expected $RESTIC_SHA256, got $actual; nothing installed" >&2
    exit 1
fi

bunzip2 -c "$work/$ASSET" > "$work/restic"
chmod 0755 "$work/restic"
mkdir -p "$install_dir"
# Rename within the target directory so a running restic never sees a half-written file.
mv "$work/restic" "$target.partial"
mv "$target.partial" "$target"
echo "installed $("$target" version | head -1) at $target"
