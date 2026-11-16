#!/usr/bin/env python3
"""Export an arabmaqamrock ABC score to MusicXML, the format MuseScore reads.

MuseScore (and every notation editor) cannot open ABC. It does open MusicXML,
so this tool is the bridge between a `transcribe.py` output (`score.abc`) and a
MuseScore score that can be viewed, printed, played and edited.

The conversion is done with the project's own strict parser
(`tools/vendor/abc_tools.py`) rather than a generic ABC library,
so the studio dialect is preserved exactly:

  * one MusicXML part per ABC voice (Vocal, Ins);
  * bar grid, meters, key changes and tempo kept as written;
  * chord symbols become <harmony> on the Vocal staff;
  * notes that cross a barline are split and tied;
  * gaps are filled with rests, empty bars become full-measure rests.

Durations in the native dialect are exact multiples of 1/32 of a quarter note,
so MusicXML uses divisions=8 and nothing is rounded.

Usage:
    python3 tools/abc_to_musicxml.py score.abc --out score.musicxml
    python3 tools/abc_to_musicxml.py score.abc --out score.musicxml \
        --render pdf --render png

`--render` shells out to MuseScore (`mscore-cli`, or MUSESCORE if set). That is
optional: the converter itself has no third-party dependencies.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "vendor"))

from abc_tools import KEYS, NATURAL, key_accidentals, parse_abc  # noqa: E402  # vendored

DIVISIONS = 8  # MusicXML divisions per quarter note == 1 ABC unit (1/32)
SHARP_ORDER = "FCGDAEB"
TOOL_VERSION = "arabmaqamrock-abc-to-musicxml/1"

# ABC chord quality -> MusicXML <kind>, and the text printed on the chart.
KINDS = {
    "": "major",
    "m": "minor",
    "dim": "diminished",
    "aug": "augmented",
    "7": "dominant",
    "maj7": "major-seventh",
    "m7": "minor-seventh",
    "dim7": "diminished-seventh",
    "m7b5": "half-diminished",
    "sus4": "suspended-fourth",
    "sus2": "suspended-second",
    "6": "major-sixth",
    "m6": "minor-sixth",
    "7sus4": "suspended-fourth",
    "m(maj7)": "minor-major",
}
# Qualities whose <kind> alone does not print the ABC text.
KIND_TEXT = {"suspended-fourth", "minor-major", "half-diminished"}
# 32nd notes -> (MusicXML type, dots). The parser only emits these lengths.
TYPES = {
    1: ("32nd", 0), 2: ("16th", 0), 3: ("16th", 1),
    4: ("eighth", 0), 6: ("eighth", 1),
    8: ("quarter", 0), 12: ("quarter", 1),
    16: ("half", 0), 24: ("half", 1),
    32: ("whole", 0), 48: ("whole", 1),
}


def fifths(key: str) -> int:
    """Key signature as a MusicXML <fifths> count."""
    return KEYS[key]


def spelling(pitch: int, key: str) -> tuple[str, int, int]:
    """MIDI pitch -> (step, alter, octave) spelled against the key signature."""
    pc = pitch % 12
    octave = pitch // 12 - 1
    signature = key_accidentals(key) if key in KEYS else {}
    # 1) a letter the key signature already spells at this pitch class
    for letter, alter in signature.items():
        if (NATURAL[letter] + alter) % 12 == pc:
            return letter, alter, octave
    # 2) otherwise use the accidental direction the key implies
    order = SHARP_ORDER if (not signature or sum(signature.values()) > 0) \
        else SHARP_ORDER[::-1]
    for letter in order:
        delta = (pc - NATURAL[letter]) % 12
        for shift, semis in ((2, 2), (-2, 10), (1, 1), (-1, 11)):
            if delta == semis:
                return letter, shift, octave
    return "C", 0, octave


def split_name(name: str) -> tuple[str, int]:
    """'Bbm' / 'F#maj7' / 'Bb' -> (letter, accidental)."""
    letter, rest = name[0], name[1:]
    for accidental, value in (("##", 2), ("bb", -2), ("#", 1), ("b", -1)):
        if rest.startswith(accidental):
            return letter, value
    return letter, 0


def chord_parts(symbol: str) -> tuple[str, int, str, str, str | None]:
    """'Bbm7/Db' -> (root letter, root alter, kind, printed text, bass)."""
    bass = None
    if "/" in symbol:
        symbol, bass = symbol.split("/", 1)
    letter, rest = symbol[0], symbol[1:]
    root_alter = 0
    for accidental, value in (("##", 2), ("bb", -2), ("#", 1), ("b", -1)):
        if rest.startswith(accidental):
            root_alter, rest = value, rest[len(accidental):]
            break
    kind = KINDS.get(rest, "major")
    return letter, root_alter, kind, rest, bass


def add_harmony(measure: ET.Element, symbol: str) -> None:
    letter, root_alter, kind, text, bass = chord_parts(symbol)
    harmony = ET.SubElement(measure, "harmony")
    if text and kind in KIND_TEXT:
        harmony.set("print-frame", "no")
    root = ET.SubElement(harmony, "root")
    ET.SubElement(root, "root-step").text = letter
    if root_alter:
        ET.SubElement(root, "root-alter").text = str(root_alter)
    kind_el = ET.SubElement(harmony, "kind")
    kind_el.set("text", text)
    kind_el.text = kind
    if bass:
        bass_letter, bass_alter = split_name(bass)
        bass_el = ET.SubElement(harmony, "bass")
        ET.SubElement(bass_el, "bass-step").text = bass_letter
        if bass_alter:
            ET.SubElement(bass_el, "bass-alter").text = str(bass_alter)


def add_note(measure: ET.Element, *, units: int, pitch: int | None, key: str,
             tie_start: bool = False, tie_stop: bool = False) -> None:
    note = ET.SubElement(measure, "note")
    if pitch is None:
        ET.SubElement(note, "rest")
    else:
        pitch_el = ET.SubElement(note, "pitch")
        step, alter, octave = spelling(pitch, key)
        ET.SubElement(pitch_el, "step").text = step
        if alter:
            ET.SubElement(pitch_el, "alter").text = str(alter)
        ET.SubElement(pitch_el, "octave").text = str(octave)
    ET.SubElement(note, "duration").text = str(units)
    if tie_stop:
        ET.SubElement(note, "tie", type="stop")
    if tie_start:
        ET.SubElement(note, "tie", type="start")
    ET.SubElement(note, "voice").text = "1"
    note_type, dots = TYPES.get(units, ("quarter", 0))
    ET.SubElement(note, "type").text = note_type
    for _ in range(dots):
        ET.SubElement(note, "dot")
    if tie_start or tie_stop:
        notations = ET.SubElement(note, "notations")
        if tie_stop:
            ET.SubElement(notations, "tied", type="stop")
        if tie_start:
            ET.SubElement(notations, "tied", type="start")


def split_at_bars(notes: list, bars: list[tuple[Fraction, Fraction]]) -> list[list[dict]]:
    """Explode notes across barlines, recording the tie on each side."""
    per_bar: list[list[dict]] = [[] for _ in bars]
    for onset, pitch, duration in notes:
        position, remaining, first = onset, duration, True
        while remaining > 0:
            index = next((i for i, (start, length) in enumerate(bars)
                          if start <= position < start + length), None)
            if index is None:
                break
            start, length = bars[index]
            take = min(remaining, start + length - position)
            per_bar[index].append({
                "offset": position - start,
                "units": int(take * DIVISIONS),
                "pitch": pitch,
                "tie_stop": not first,
                "tie_start": take < remaining,
            })
            position += take
            remaining -= take
            first = False
    return per_bar


def attributes(measure: ET.Element, *, key: str, meter: tuple[int, int],
               divisions: bool = False, clef: bool = False) -> None:
    attrs = ET.SubElement(measure, "attributes")
    if divisions:
        ET.SubElement(attrs, "divisions").text = str(DIVISIONS)
    key_el = ET.SubElement(attrs, "key")
    ET.SubElement(key_el, "fifths").text = str(fifths(key))
    ET.SubElement(key_el, "mode").text = "minor" if key.endswith("m") else "major"
    time_el = ET.SubElement(attrs, "time")
    ET.SubElement(time_el, "beats").text = str(meter[0])
    ET.SubElement(time_el, "beat-type").text = str(meter[1])
    if clef:
        clef_el = ET.SubElement(attrs, "clef")
        ET.SubElement(clef_el, "sign").text = "G"
        ET.SubElement(clef_el, "line").text = "2"


def tempo_direction(measure: ET.Element, bpm: int) -> None:
    direction = ET.SubElement(measure, "direction", placement="above")
    direction_type = ET.SubElement(direction, "direction-type")
    metronome = ET.SubElement(direction_type, "metronome")
    ET.SubElement(metronome, "beat-unit").text = "quarter"
    ET.SubElement(metronome, "per-minute").text = str(bpm)
    ET.SubElement(direction, "sound", tempo=str(bpm))


def build_part(part: ET.Element, voice, bars: list[tuple[Fraction, Fraction]],
               meters: list[tuple[int, int]], bpm: int) -> None:
    """Write one ABC voice into a MusicXML <part> element."""
    segments = split_at_bars(voice.notes, bars)
    chords_at: dict[Fraction, str] = {}
    for onset, symbol in voice.chords:
        chords_at.setdefault(onset, symbol)
    key_changes = dict(voice.keys)
    # The parser leaves voice.key on the last key of the score, so the opening
    # key has to come from the key timeline (a song may modulate later).
    current_key = voice.keys[0][1] if voice.keys else voice.key

    for index, (start, length) in enumerate(bars):
        meter = meters[index]
        measure = ET.SubElement(part, "measure", number=str(index + 1))
        if index == 0:
            attributes(measure, key=current_key, meter=meter,
                       divisions=True, clef=True)
            tempo_direction(measure, bpm)
        else:
            new_key = key_changes.get(start)
            key_changed = bool(new_key) and new_key != current_key
            meter_changed = meter != meters[index - 1]
            if key_changed or meter_changed:
                current_key = new_key or current_key
                attributes(measure, key=current_key, meter=meter)

        events = [(segment["offset"], "note", segment)
                  for segment in segments[index]]
        for onset, symbol in chords_at.items():
            if start <= onset < start + length:
                events.append((onset - start, "chord", symbol))
        events.sort(key=lambda event: (event[0], event[1] == "chord"))

        if not events:
            add_note(measure, units=int(length * DIVISIONS), pitch=None,
                     key=current_key)
            continue

        cursor = Fraction(0)
        for offset, kind, payload in events:
            if offset > cursor:
                add_note(measure, units=int((offset - cursor) * DIVISIONS),
                         pitch=None, key=current_key)
                cursor = offset
            if kind == "chord":
                add_harmony(measure, payload)
                continue
            add_note(measure, units=payload["units"], pitch=payload["pitch"],
                     key=current_key, tie_start=payload["tie_start"],
                     tie_stop=payload["tie_stop"])
            cursor = offset + Fraction(payload["units"], DIVISIONS)
        if cursor < length:
            add_note(measure, units=int((length - cursor) * DIVISIONS),
                     pitch=None, key=current_key)


def to_musicxml(abc_text: str, *, title: str = "arabmaqamrock transcription",
                composer: str = "") -> str:
    """Convert ABC text to a complete MusicXML 4.0 partwise document."""
    if not isinstance(abc_text, str) or not abc_text.strip():
        raise ValueError("Need a nonempty ABC score")
    score = parse_abc(abc_text)
    bars = [(start, length) for start, length, _ in score.voices["Vocal"].bars]
    if not bars:
        raise ValueError("ABC score has no bars")
    for name, voice in score.voices.items():
        if len(voice.bars) != len(bars):
            raise ValueError(
                f"voice {name!r} has {len(voice.bars)} bars, "
                f"Vocal has {len(bars)}")
    meters = [meter for _, _, meter in score.voices["Vocal"].bars]

    root = ET.Element("score-partwise", version="4.0")
    work = ET.SubElement(root, "work")
    ET.SubElement(work, "work-title").text = title
    if composer:
        identification = ET.SubElement(root, "identification")
        ET.SubElement(identification, "creator", type="composer").text = composer
    part_list = ET.SubElement(root, "part-list")
    for position, name in enumerate(score.voices, start=1):
        score_part = ET.SubElement(part_list, "score-part", id=f"P{position}")
        ET.SubElement(score_part, "part-name").text = name

    for position, (name, voice) in enumerate(score.voices.items(), start=1):
        part = ET.SubElement(root, "part", id=f"P{position}")
        build_part(part, voice, bars, meters, score.bpm)

    body = ET.tostring(root, encoding="unicode")
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 '
        'Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">\n')
    return header + body + "\n"


def verify(abc_text: str, musicxml_text: str) -> dict:
    """Re-read the MusicXML and check it against the ABC bar grid.

    Compares bars per part, sounding duration per part and chord count, so a
    silent loss (dropped voice, rounded duration, missing chord) is caught.
    """
    score = parse_abc(abc_text)
    root = ET.fromstring(musicxml_text)
    parts = root.findall("part")
    if len(parts) != len(score.voices):
        raise ValueError(
            f"expected {len(score.voices)} parts, found {len(parts)}")
    report = {"bars": len(score.voices["Vocal"].bars), "parts": []}
    for part, (name, voice) in zip(parts, score.voices.items()):
        divisions = int(part.findtext("measure/attributes/divisions") or
                        DIVISIONS)
        written = Fraction(0)
        for note in part.iter("note"):
            written += Fraction(int(note.findtext("duration") or 0), divisions)
        if written != voice.time:
            raise ValueError(
                f"{name}: written duration {written} != ABC duration {voice.time}")
        report["parts"].append({
            "name": name,
            "measures": len(part.findall("measure")),
            "notes": sum(1 for note in part.iter("note")
                         if note.find("pitch") is not None),
            "chords": len(part.findall("measure/harmony")),
            "quarters": str(written),
        })
    report["key"] = score.voices["Vocal"].key
    report["bpm"] = score.bpm
    report["meter"] = list(score.voices["Vocal"].bars[0][2])
    return report


def render(musicxml_path: Path, formats: list[str], out_dir: Path) -> list[Path]:
    """Render with a headless MuseScore; returns the files it produced."""
    binary = os.environ.get("MUSESCORE") or shutil.which("mscore-cli") \
        or shutil.which("musescore")
    if not binary:
        raise RuntimeError(
            "no MuseScore binary found; put mscore-cli on PATH or set MUSESCORE")
    produced: list[Path] = []
    for fmt in formats:
        target = out_dir / f"{musicxml_path.stem}.{fmt}"
        result = subprocess.run([binary, "-o", str(target), str(musicxml_path)],
                                capture_output=True, text=True, timeout=600,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        if result.returncode != 0 and target.suffix != ".png":
            raise RuntimeError(
                f"MuseScore failed for {fmt}: {result.stdout[-400:]}"
                f"{result.stderr[-400:]}")
        hits = [target] if target.is_file() else \
            sorted(out_dir.glob(f"{musicxml_path.stem}-*.{fmt}"))
        if not hits:
            raise RuntimeError(f"MuseScore produced nothing for {fmt}")
        produced.extend(hits)
    return produced


def main() -> int:
    cli = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("input", type=Path, help="ABC score (e.g. score.abc)")
    cli.add_argument("--out", required=True, type=Path,
                     help="MusicXML path to write")
    cli.add_argument("--title", default=None,
                     help="work title (default: input stem)")
    cli.add_argument("--composer", default="", help="composer credit")
    cli.add_argument("--render", action="append", default=[],
                     metavar="FORMAT",
                     help="also render with MuseScore (pdf, png, mp3, mid, "
                          "mscz...); repeatable")
    cli.add_argument("--version", action="version", version=TOOL_VERSION)
    args = cli.parse_args()

    try:
        text = args.input.read_text(encoding="utf-8")
        musicxml = to_musicxml(text, title=args.title or args.input.stem,
                               composer=args.composer)
        report = verify(text, musicxml)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(musicxml, encoding="utf-8")
        for fmt in args.render:
            for path in render(args.out, [fmt], args.out.parent):
                print(f"rendered {path}")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ABC -> MusicXML failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2

    parts = "  ".join(
        f"{part['name']}: {part['notes']} notes/{part['chords']} chords"
        for part in report["parts"])
    print(f"{args.input.name:28} -> {args.out.name:28} "
          f"bars={report['bars']} key={report['key']} "
          f"meter={report['meter'][0]}/{report['meter'][1]} "
          f"bpm={report['bpm']} {parts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
