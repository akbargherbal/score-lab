#!/usr/bin/env bash
# take_shot.sh — screenshot a WSLg window (MuseScore by default) from WSL.
#
# WSLg renders Linux windows as Windows windows (hosted by msrdc), so an
# in-WSL X capture (scrot/xwd) comes out blank. This wrapper delegates to
# window-shot.ps1, which runs on the Windows side and copies the real pixels.
#
# MuseScore titles its window after the open score (e.g. "demo.musicxml
# (Ubuntu-22.04)"), not "MuseScore" — with no title argument the script picks
# the largest WSLg window instead of matching an app name.
#
# Usage:
#   tools/take_shot.sh <out.png> [title-substring] [options]
#   tools/take_shot.sh --list
#
# Examples:
#   tools/take_shot.sh /tmp/ms.png                 # largest WSLg window
#   tools/take_shot.sh /tmp/demo.png demo          # window whose title has "demo"
#   tools/take_shot.sh /tmp/aud.png Audacity       # native Windows app too
#   tools/take_shot.sh --list                      # what can be captured?
#   tools/take_shot.sh /tmp/ms.png --client        # drop the Windows title bar
#   tools/take_shot.sh /tmp/ms.png --wait 15       # wait for the window to appear
#
# Options:
#   --client            capture the client area (no Windows frame)
#   --wait SECONDS      retry up to N seconds while the window does not exist
#   --list              print visible windows (wslg/win, size, title) and exit
#   --maximize          maximize before capture (off by default)
#   --keep-cursor       do not park the pointer in the corner first
#                       (parking avoids taskbar/tooltip flyouts in the shot)
#
# Environment:
#   SHOT_TITLE            default title substring (empty = largest WSLg window)
#   SHOT_AUTO_FOCUS=0     never restore/raise the window (error instead)
#   SHOT_AUTO_MAXIMIZE=1  same as --maximize
#   SHOT_PARK_CURSOR=0    leave the pointer where it is
#
# Exit codes: 0 captured, 1 usage/interop/missing window/capture failure.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PS1="$HERE/window-shot.ps1"

OUT=""
TITLE="${SHOT_TITLE:-}"
CLIENT=0
WAIT=0
MAXIMIZE="${SHOT_AUTO_MAXIMIZE:-0}"
LIST=0
PARK="${SHOT_PARK_CURSOR:-1}"

want_value=""
for arg in "$@"; do
    if [ -n "$want_value" ]; then
        case "$want_value" in
            wait) WAIT="$arg" ;;
        esac
        want_value=""
        continue
    fi
    case "$arg" in
        -l|--list) LIST=1 ;;
        --client) CLIENT=1 ;;
        --maximize) MAXIMIZE=1 ;;
        --keep-cursor) PARK=0 ;;
        --wait) want_value="wait" ;;
        --wait=*) WAIT="${arg#--wait=}" ;;
        -h|--help) sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "ERROR:BAD_ARG: unknown option $arg" >&2; exit 1 ;;
        *)
            if [ -z "$OUT" ]; then OUT="$arg"; else TITLE="$arg"; fi
            ;;
    esac
done

command -v powershell.exe >/dev/null || {
    echo "ERROR:NO_POWERSHELL: powershell.exe not on PATH — is WSL interop enabled?" >&2
    exit 1
}
PS1_WIN="$(wslpath -w "$PS1")"

run_ps() {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_WIN" "$@" 2>&1 | tr -d '\r'
}

if [ "$LIST" -eq 1 ]; then
    run_ps -List
    exit $?
fi

if [ -z "$OUT" ]; then
    echo "Usage: $0 <out.png> [title-substring] [--client] [--wait N] | --list" >&2
    exit 1
fi

mkdir -p "$(dirname "$OUT")"
OUT_WIN="$(wslpath -w "$OUT")"

TITLE_FILE=""
if [ -n "$TITLE" ]; then
    TITLE_FILE="$(mktemp /tmp/opencode/shot-title.XXXXXX 2>/dev/null || mktemp)"
    printf '%s' "$TITLE" > "$TITLE_FILE"
fi
ARGS=(-OutFile "$OUT_WIN" -TitleFile "$(wslpath -w "$TITLE_FILE")"
      -AutoFocus "${SHOT_AUTO_FOCUS:-1}" -AutoMaximize "$MAXIMIZE" \
      -ParkCursor "$PARK")
[ "$CLIENT" -eq 1 ] && ARGS+=(-ClientArea)

deadline=$(( $(date +%s) + WAIT ))
while :; do
    set +e
    RESULT="$(run_ps "${ARGS[@]}")"
    STATUS=$?
    set -e
    if [ "$STATUS" -eq 0 ] && grep -qx "OK" <<<"$RESULT"; then
        break
    fi
    if ! grep -q "^ERROR:NOT_FOUND:" <<<"$RESULT" || [ "$(date +%s)" -ge "$deadline" ]; then
        grep -E "^(ERROR|NOTE|VISIBLE):" <<<"$RESULT" >&2 || echo "$RESULT" >&2
        exit 1
    fi
    sleep 1
done

[ -n "$TITLE_FILE" ] && rm -f "$TITLE_FILE"
if [ ! -s "$OUT" ]; then
    echo "ERROR:FILE_MISSING: PowerShell reported OK but $OUT is missing or empty" >&2
    exit 1
fi

grep -E "^(TITLE|SIZE|NOTE):" <<<"$RESULT"
echo "Saved: $OUT ($(stat -c %s "$OUT") bytes)"
