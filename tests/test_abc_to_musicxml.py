#!/usr/bin/env python3
"""Unit tests for tools/abc_to_musicxml.py. No network, no MuseScore."""
from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "vendor"))

import abc_to_musicxml  # noqa: E402

# Two bars of 2/4 in the studio dialect: the Vocal staff carries chords only,
# the Ins staff has a tie across the barline and a leading rest.
SMALL = """X:1
T:
M:2/4
L:1/32
Q:1/4=90
V: Vocal clef=treble name="Vocal Melody" snm="Vocal"
V: Ins clef=treble name="Ins Melody" snm="Inst."
K:Bbm
V: Vocal
"Bbm"z16|"Fm7"z16|
V: Ins
z8b8-|b8z8|
"""

# Modulation in the middle plus a chord with an added bass note.
MODULATING = """X:1
T:
M:3/4
L:1/32
Q:1/4=68
V: Vocal clef=treble name="Vocal Melody" snm="Vocal"
V: Ins clef=treble name="Ins Melody" snm="Inst."
K:Bbm
V: Vocal
"Bbm"z24|[K:A]"A"z24|
V: Ins
d'8b8z8|[K:A]a24|
"""


class ToMusicXmlTests(unittest.TestCase):
    def setUp(self):
        self.xml = abc_to_musicxml.to_musicxml(SMALL, title="t")
        self.root = ET.fromstring(self.xml)

    def test_one_part_per_voice_with_two_bars_each(self):
        parts = self.root.findall("part")
        self.assertEqual(len(parts), 2)
        for part in parts:
            self.assertEqual(len(part.findall("measure")), 2)

    def test_header_carries_key_meter_and_tempo(self):
        attrs = self.root.find("part/measure/attributes")
        self.assertEqual(attrs.findtext("divisions"), "8")
        self.assertEqual(attrs.findtext("key/fifths"), "-5")
        self.assertEqual(attrs.findtext("key/mode"), "minor")
        self.assertEqual(attrs.findtext("time/beats"), "2")
        self.assertEqual(attrs.findtext("time/beat-type"), "4")
        tempo = self.root.find("part/measure/direction/sound")
        self.assertEqual(tempo.get("tempo"), "90")

    def test_chords_land_on_the_vocal_staff_only(self):
        vocal, ins = self.root.findall("part")
        harmonies = vocal.findall("measure/harmony")
        self.assertEqual(len(harmonies), 2)
        self.assertEqual(harmonies[0].findtext("root/root-step"), "B")
        self.assertEqual(harmonies[0].findtext("root/root-alter"), "-1")
        self.assertEqual(harmonies[0].findtext("kind"), "minor")
        self.assertEqual(harmonies[1].findtext("kind"), "minor-seventh")
        self.assertEqual(ins.findall("measure/harmony"), [])

    def test_tie_across_barline_is_split_and_tied(self):
        ins = self.root.findall("part")[1]
        first, second = ins.findall("measure")
        tail = [n for n in first.iter("note") if n.find("pitch") is not None][-1]
        head = [n for n in second.iter("note") if n.find("pitch") is not None][0]
        self.assertEqual(tail.findtext("pitch/step"), "B")
        self.assertEqual(tail.findtext("pitch/alter"), "-1")
        self.assertEqual(tail.findtext("type"), "quarter")
        self.assertIsNotNone(tail.find("tie[@type='start']"))
        self.assertIsNotNone(head.find("tie[@type='stop']"))
        self.assertIsNotNone(head.find("notations/tied[@type='stop']"))
        self.assertEqual(head.findtext("duration"), "8")

    def test_rests_fill_the_gaps(self):
        ins = self.root.findall("part")[1]
        first = ins.find("measure")
        notes = list(first.iter("note"))
        self.assertIsNotNone(notes[0].find("rest"))
        self.assertEqual(notes[0].findtext("duration"), "8")
        total = sum(int(n.findtext("duration")) for n in notes)
        self.assertEqual(total, 16)  # 2/4 == 16 units of 1/32

    def test_verify_reports_the_source_shape(self):
        report = abc_to_musicxml.verify(SMALL, self.xml)
        self.assertEqual(report["bars"], 2)
        self.assertEqual(report["key"], "Bbm")
        self.assertEqual(report["bpm"], 90)
        self.assertEqual(report["meter"], [2, 4])
        vocal, ins = report["parts"]
        self.assertEqual(vocal["name"], "Vocal")
        self.assertEqual(vocal["chords"], 2)
        self.assertEqual(vocal["notes"], 0)
        self.assertEqual(ins["name"], "Ins")
        self.assertEqual(ins["notes"], 2)
        self.assertEqual(ins["quarters"], "4")  # two bars of 2/4

    def test_verify_catches_a_dropped_bar(self):
        root = ET.fromstring(self.xml)
        part = root.findall("part")[1]
        part.remove(part[-1])
        tampered = ET.tostring(root, encoding="unicode")
        with self.assertRaises(ValueError):
            abc_to_musicxml.verify(SMALL, tampered)

    def test_spelling_follows_the_key_signature(self):
        self.assertEqual(abc_to_musicxml.spelling(70, "Bbm"), ("B", -1, 4))
        self.assertEqual(abc_to_musicxml.spelling(85, "Bbm"), ("D", -1, 6))
        self.assertEqual(abc_to_musicxml.spelling(60, "Bbm"), ("C", 0, 4))
        self.assertEqual(abc_to_musicxml.spelling(66, "D"), ("F", 1, 4))
        self.assertEqual(abc_to_musicxml.spelling(73, "Bbm"), ("D", -1, 5))
        self.assertEqual(abc_to_musicxml.spelling(69, "D"), ("A", 0, 4))

    def test_chord_parts_handles_accidentals_and_slash_bass(self):
        self.assertEqual(abc_to_musicxml.chord_parts("Bbm7"),
                         ("B", -1, "minor-seventh", "m7", None))
        self.assertEqual(abc_to_musicxml.chord_parts("F#dim7/G"),
                         ("F", 1, "diminished-seventh", "dim7", "G"))
        self.assertEqual(abc_to_musicxml.chord_parts("C"),
                         ("C", 0, "major", "", None))

    def test_modulation_and_compound_meter(self):
        xml = abc_to_musicxml.to_musicxml(MODULATING)
        ins = ET.fromstring(xml).findall("part")[1]
        self.assertEqual(ins.findtext("measure/attributes/time/beats"), "3")
        # The opening key stays Bbm even though the score modulates later.
        self.assertEqual(ins.findtext("measure/attributes/key/fifths"), "-5")
        second = ins.findall("measure")[1]
        self.assertEqual(second.findtext("attributes/key/fifths"), "3")
        self.assertEqual(ins.find("measure").findtext(".//harmony/kind"), None)
        report = abc_to_musicxml.verify(MODULATING, xml)
        self.assertEqual(report["parts"][1]["quarters"], "6")  # two bars of 3/4

    def test_empty_or_broken_input_is_rejected(self):
        for text in ("", "   "):
            with self.assertRaises(ValueError):
                abc_to_musicxml.to_musicxml(text)
        with self.assertRaises(ValueError):
            abc_to_musicxml.to_musicxml(
                "X:1\nT:\nM:2/4\nL:1/32\nQ:1/4=90\nK:C\n")


if __name__ == "__main__":
    unittest.main()
