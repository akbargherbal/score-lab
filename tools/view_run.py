#!/usr/bin/env python3
"""Build a synchronized viewer for every transcript in a run, plus an index.

`score_viewer.py` handles one track. This is the batch wrapper for a whole
transcripts tree:

    <run>/transcripts/<take>/     score.abc + the .lab files   (transcribe.py)
    <run>/<take>.musicxml         only needed for the score pages
                                  (abc_to_musicxml.py)
    <take>.mp3                    the take's audio, in --audio-dir

It writes, per take, `<out>/<take>/{viewer.html,audio.mp3}` (+ `pages/` when
page images are built) and an `<out>/index.html` gallery.

With `--no-pages` nothing touches MuseScore or MusicXML: the viewer is built
from the .lab files + audio alone. That is the default choice when you only
want the waveform, chords, sections and piano roll.

Usage:
    python3 tools/view_run.py --run ~/score-view/<run> \
        --transcripts transcripts \
        --audio-dir gs://<bucket>/.../<run> \
        --out ~/score-view/<run> --no-pages

`--audio-dir` accepts a gs:// prefix (fetched with gcloud) or a local
directory; audio already present is never re-downloaded, and built pages are
reused.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VIEWER = HERE / "score_viewer.py"
MSCORE = shutil.which("mscore-cli") or str(HERE / "mscore-cli")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def pages_for(musicxml: Path, track_out: Path) -> list[Path]:
    pages = track_out / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    existing = sorted(pages.glob("p-*.png"))
    if existing:
        return existing
    run([MSCORE, "-o", str(pages / "raw.png"), str(musicxml)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    from PIL import Image  # only needed for thumbnailing

    for f in sorted(pages.glob("raw-*.png")):
        idx = f.name.rsplit("-", 1)[-1]
        im = Image.open(f).convert("RGB")
        im.thumbnail((1000, 1414))
        im.save(pages / f"p-{idx}", optimize=True)
        f.unlink()
    return sorted(pages.glob("p-*.png"),
                  key=lambda p: int(re.search(r"p-(\d+)", p.name).group(1)))


def audio_for(take: str, track_out: Path, audio_dir: str) -> Path:
    audio = track_out / "audio.mp3"
    if audio.is_file() and audio.stat().st_size > 0:
        return audio
    if audio_dir.startswith("gs://"):
        run(["gcloud", "storage", "cp", f"{audio_dir.rstrip('/')}/{take}.mp3",
             str(audio)])
    else:
        shutil.copy2(Path(audio_dir) / f"{take}.mp3", audio)
    return audio


def header(score_abc: Path) -> dict:
    head = score_abc.read_text().splitlines()[:8]
    get = lambda p: next(l[2:] for l in head if l.startswith(p))  # noqa: E731
    return {
        "key": get("K:"),
        "meter": get("M:"),
        "bpm": int(next(l for l in head if l.startswith("Q:")).split("=")[1]),
    }


INDEX = """<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>عارضات السكور — {run}</title>
<style>
 body{{margin:0;background:#14171c;color:#e8eaef;font:14px/1.5 system-ui,"Segoe UI",sans-serif}}
 header{{padding:16px 20px;border-bottom:1px solid #262c35;background:#1c2129}}
 h1{{margin:0;font-size:17px}}
 .sub{{color:#8b93a1;font-size:12.5px;margin-top:4px}}
 table{{border-collapse:collapse;width:100%}}
 th,td{{padding:8px 10px;border-bottom:1px solid #222831;text-align:right;white-space:nowrap}}
 th{{color:#8b93a1;font-weight:500;font-size:12px;position:sticky;top:0;background:#14171c}}
 tr:hover{{background:#1a1f27}}
 a{{color:#4ea1ff;text-decoration:none}}
 a:hover{{text-decoration:underline}}
 img{{width:72px;border-radius:3px;background:#fff}}
 .num{{font-variant-numeric:tabular-nums;color:#b9c2cf}}
</style></head><body>
<header><h1>عارضات السكور المتزامنة — {n} take</h1>
<div class="sub">{run}</div></header>
<table><thead><tr>{cover_th}<th>take</th><th>مدّة</th><th>مقام</th>
<th>ميزان</th><th>BPM</th><th>بارات</th><th>كوردات</th>{pages_th}
<th>رندر الموديل</th></tr></thead><tbody>
{rows}
</tbody></table></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=Path, required=True,
                    help="generation run dir: it holds <transcripts>/<take>/ "
                         "with score.abc + the .lab files, and <take>.musicxml")
    ap.add_argument("--out", type=Path, default=None,
                    help="where <take>/viewer.html + index.html go "
                         "(default: the --run dir itself)")
    ap.add_argument("--audio-dir", required=True,
                    help="where the takes' audio lives: a gs:// prefix or a "
                         "local dir containing <take>.mp3")
    ap.add_argument("--transcripts", default="transcripts", metavar="DIR",
                    help="subdirectory of --run holding the takes "
                         "(default: transcripts)")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--force", action="store_true", help="rebuild viewers")
    ap.add_argument("--no-pages", action="store_true",
                    help="notation-free viewer (waveform/chords/sections/piano "
                         "roll only): no MuseScore, no MusicXML, no page images")
    args = ap.parse_args()

    out_root = (args.out or args.run).expanduser()
    src = args.run.expanduser() / args.transcripts
    takes = sorted(p for p in src.iterdir() if (p / "score.abc").is_file())
    if args.limit:
        takes = takes[:args.limit]
    if not takes:
        print(f"no transcripts under {src}", file=sys.stderr)
        return 2

    rows = []
    for i, track in enumerate(takes, 1):
        name = track.name
        track_out = out_root / name
        viewer = track_out / "viewer.html"
        musicxml = args.run.expanduser() / f"{name}.musicxml"
        if args.force or not viewer.is_file():
            if not args.no_pages and not musicxml.is_file():
                print(f"skip {name}: no {musicxml.name} (run abc_to_musicxml.py first)",
                      file=sys.stderr)
                continue
            track_out.mkdir(parents=True, exist_ok=True)
            audio = audio_for(name, track_out, args.audio_dir)
            pages = [] if args.no_pages else pages_for(musicxml, track_out)
            cmd = [sys.executable, str(VIEWER), "--abc", str(track),
                   "--audio", str(audio), "--out", str(viewer), "--title", name]
            if pages:
                cmd += ["--pages", str(track_out / "pages")]
            run(cmd)
        else:
            audio = track_out / "audio.mp3"
            pages = [] if args.no_pages else sorted(
                (track_out / "pages").glob("p-*.png"))

        info = header(track / "score.abc")
        meta = json.loads((track / "meta.json").read_text())
        dur = float(run(["ffprobe", "-v", "error", "-show_entries",
                         "format=duration", "-of", "default=nk=1:nw=1",
                         str(audio)]).stdout)
        m, s = divmod(int(dur), 60)
        bars = len((track / "downbeat.lab").read_text().splitlines())
        chords = len((track / "chord.lab").read_text().splitlines())
        rows.append(
            "<tr>"
            + (f'<td><a href="{name}/viewer.html"><img src="{name}/pages/{pages[0].name}" alt=""></a></td>'
               if pages else "")
            + f'<td><a href="{name}/viewer.html">{name}</a></td>'
            + f'<td class="num">{m}:{s:02d}</td>'
            f'<td>{info["key"]}</td><td>{info["meter"]}</td>'
            f'<td class="num">{info["bpm"]}</td><td class="num">{bars}</td>'
            f'<td class="num">{chords}</td>'
            + (f'<td class="num">{len(pages)}</td>' if pages else "")
            + f'<td class="num">{(meta.get("seconds") or 0):.0f}s</td>'
            "</tr>")
        print(f"[{i}/{len(takes)}] {name}  {dur:.0f}s  {bars} bars  "
              f"{len(pages)} pages", flush=True)

    (out_root / "index.html").write_text(
        INDEX.format(run=args.run.name, n=len(rows), rows="\n".join(rows),
                     cover_th="<th>غلاف</th>" if not args.no_pages else "",
                     pages_th="" if args.no_pages else "<th>صفحات</th>"),
        encoding="utf-8")
    print(f"\nindex: {out_root / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
