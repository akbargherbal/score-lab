#!/usr/bin/env bash
# take_shot.sh — screenshot a WSLg window (by default: MuseScore) from WSL.
#
# WSLg renders Linux windows as Windows windows (hosted by msrdc), so an
# in-WSL X capture (scrot/xwd) comes out blank. This wrapper delegates to
# window-shot.ps1, which runs on the Windows side and copies the real pixels.
#
# MuseScore titles its window after the open score (e.g. "demo.musicxml
# (Ubuntu-22.04)"), not "MuseScore" — so with no argument the script picks the
# largest WSLg window instead of matching an app name.
#
# Usage:
#   tools/take_shot.sh <out.png> [title-substring]
#
# Examples:
#   tools/take_shot.sh /tmp/musescore.png          # any WSLg window
#   tools/take_shot.sh /tmp/demo.png demo          # a score whose title has "demo"
#   tools/take_shot.sh /tmp/other.png Audacity     # a native Windows app too
#
# Environment:
#   SHOT_TITLE          default title substring (default: empty = any WSLg window)
#   SHOT_AUTO_FOCUS=0   never restore/raise the window (error instead)
#   SHOT_AUTO_MAXIMIZE=0  capture at the current window size
#
# Exit codes: 0 captured, 1 usage/interop/missing window/capture failure.
set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <out.png> [title-substring]" >&2
    exit 1
fi

OUT="$1"
TITLE="${2:-${SHOT_TITLE:-}}"
AUTO_FOCUS="${SHOT_AUTO_FOCUS:-1}"
AUTO_MAXIMIZE="${SHOT_AUTO_MAXIMIZE:-1}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PS1="$HERE/window-shot.ps1"

command -v powershell.exe >/dev/null || {
    echo "ERROR:NO_POWERSHELL: powershell.exe not on PATH — is WSL interop enabled?" >&2
    exit 1
}

mkdir -p "$(dirname "$OUT")"
OUT_WIN="$(wslpath -w "$OUT")"
PS1_WIN="$(wslpath -w "$PS1")"

set +e
RESULT="$(powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_WIN" \
    -OutFile "$OUT_WIN" -Title "$TITLE" \
    -AutoFocus "$AUTO_FOCUS" -AutoMaximize "$AUTO_MAXIMIZE" 2>&1 | tr -d '\r')"
STATUS=$?
set -e

if [ "$STATUS" -ne 0 ] || ! grep -qx "OK" <<<"$RESULT"; then
    echo "$RESULT" | grep -E "^(ERROR|NOTE):" >&2 || echo "$RESULT" >&2
    exit 1
fi

if [ ! -s "$OUT" ]; then
    echo "ERROR:FILE_MISSING: PowerShell reported OK but $OUT is missing or empty" >&2
    exit 1
fi

grep -E "^(TITLE|SIZE|NOTE):" <<<"$RESULT"
echo "Saved: $OUT ($(stat -c %s "$OUT") bytes)"
