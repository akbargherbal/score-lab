#!/usr/bin/env python3
"""Build a synchronized viewer: real audio + the model's symbols, one timeline.

Inputs are the SheetSage2 side artifacts that `transcribe.py` already writes:

  score.abc                 header only (key, meter, tempo, bar count)
  beat.lab  downbeat.lab    real timestamps of beats / bar starts
  chord.lab structure.lab   time-ranged labels
  melody_vocal.lab          start end midi_pitch
  melody_instrumental.lab   start end midi_pitch

Plus an audio file (the take) and the engraved pages (PNG, one per page).

Output is a self-contained page: waveform, bar grid, chord lane, section lane,
piano roll, and the engraved page for the current bar, all driven by the audio
element's currentTime. No network, no dependencies, opens from file://.

Usage:
    python3 tools/score_viewer.py --abc <track dir> --audio <take.mp3> \
        --pages <page-pngs> --out <out dir>/viewer.html --title "..."

Build the page images first, then the viewer:

    mscore-cli -o pages/raw.png score.musicxml      # one PNG per page
    # downscale raw-*.png -> pages/p-*.png (see docs/synchronized-viewer.md)
    python3 tools/score_viewer.py --abc <track dir> --audio take.mp3 \
        --pages pages --out viewer.html

Open the HTML from the same directory as the audio and pages/ (relative
paths, file:// friendly, no server needed).
"""
from __future__ import annotations

import argparse
import array
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "viewer-template.html"

PRETTY = {"min": "m", "maj": "", "dim": "dim", "aug": "aug", "hdim": "m7b5"}


def pretty_chord(raw: str) -> str:
    """'Eb:maj' -> 'Eb', 'D:min' -> 'Dm', 'G:min7' -> 'Gm7'."""
    if ":" not in raw:
        return raw
    root, quality = raw.split(":", 1)
    for suffix, repl in PRETTY.items():
        if quality == suffix:
            return root + repl
        if quality.startswith(suffix) and suffix not in ("maj",):
            return root + repl + quality[len(suffix):]
    return root + quality


def read_pairs(path: Path) -> list[list[float]]:
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(line.split())
    return rows


def read_ranged(path: Path) -> list[list]:
    """start end label  (label may contain spaces)."""
    out = []
    for parts in read_pairs(path):
        out.append([float(parts[0]), float(parts[1]), " ".join(parts[2:])])
    return out


def read_melody(path: Path) -> list[list[float]]:
    return [[float(a), float(b), int(float(c))] for a, b, c in read_pairs(path)]


def peaks_from_audio(audio: Path, buckets: int = 3000) -> list[list[float]]:
    """Mono 4 kHz PCM -> [lo, hi] per bucket, normalised to the loudest bucket."""
    raw = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(audio),
         "-ac", "1", "-ar", "4000", "-f", "s16le", "-"],
        capture_output=True, check=True).stdout
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":
        samples.byteswap()
    step = max(1, len(samples) // buckets)
    out = []
    for i in range(0, len(samples), step):
        chunk = samples[i:i + step]
        if not chunk:
            break
        lo, hi = min(chunk), max(chunk)
        out.append([lo / 32768.0, hi / 32768.0])
    peak = max(max(abs(lo), abs(hi)) for lo, hi in out) or 1.0
    return [[lo / peak, hi / peak] for lo, hi in out]


def parse_score_header(abc: Path) -> dict:
    head = abc.read_text().splitlines()[:8]
    get = lambda p: next(l[2:] for l in head if l.startswith(p))  # noqa: E731
    meter = get("M:")
    bpm = int(next(l for l in head if l.startswith("Q:")).split("=")[1])
    return {"key": get("K:"), "meter": [int(x) for x in meter.split("/")],
            "bpm": bpm}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--abc", type=Path, required=True, help="track dir with .lab files")
    ap.add_argument("--audio", type=Path, required=True)
    ap.add_argument("--pages", type=Path, required=True, help="dir of p-N.png")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--title", default=None)
    args = ap.parse_args()

    header = parse_score_header(args.abc / "score.abc")
    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(args.audio)],
        capture_output=True, text=True, check=True).stdout)

    bars = [float(r[0]) for r in read_pairs(args.abc / "downbeat.lab")]
    bars = [b for b in bars if b < duration]
    beats = [[float(r[0]), int(float(r[1]))]
             for r in read_pairs(args.abc / "beat.lab") if float(r[0]) < duration]
    chords = [[a, b, pretty_chord(c)] for a, b, c in
              read_ranged(args.abc / "chord.lab") if a < duration]
    sections = [[a, b, c] for a, b, c in
                read_ranged(args.abc / "structure.lab") if a < duration]
    notes = [[a, b, p, 0] for a, b, p in read_melody(args.abc / "melody_vocal.lab")]
    notes += [[a, b, p, 1] for a, b, p in
              read_melody(args.abc / "melody_instrumental.lab")]

    pages = sorted(args.pages.glob("p-*.png"),
                   key=lambda p: int(re.search(r"p-(\d+)", p.name).group(1)))
    if not pages:
        print("no page images found", file=sys.stderr)
        return 2

    data = {
        "duration": round(duration, 3),
        "bars": [round(b, 4) for b in bars],
        "beats": beats,
        "chords": chords,
        "sections": sections,
        "notes": notes,
        "peaks": peaks_from_audio(args.audio),
        "pages": [f"{args.pages.name}/{p.name}" for p in pages],
        "barsPerPage": max(1, len(bars) / len(pages)),
        "zoomSpan": 8 * (duration / max(1, len(bars))),
        "key": header["key"],
        "meter": header["meter"],
        "bpm": header["bpm"],
        "audio": args.audio.name,
        "totalBars": len(bars) + 1,
    }

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__TITLE__", args.title or args.out.stem)
    html = html.replace("__AUDIO__", args.audio.name)
    html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    args.out.write_text(html, encoding="utf-8")
    print(f"wrote {args.out}  ({args.out.stat().st_size/1024:.0f} KB, "
          f"{len(bars)} bars, {len(chords)} chords, {len(notes)} notes, "
          f"{len(pages)} pages, {duration:.0f}s audio)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
