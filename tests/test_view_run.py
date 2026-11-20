#!/usr/bin/env python3
"""Unit tests for tools/view_run.py take discovery. No audio, no MuseScore."""
from __future__ import annotations

import sys
import tarfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import view_run  # noqa: E402


def make_take(root: Path, name: str) -> Path:
    track = root / name
    track.mkdir(parents=True)
    (track / "score.abc").write_text("X:1\n")
    return track


def names(takes) -> list[str]:
    return [name for name, _ in takes]


class DiscoverTakes(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cache = self.tmp / "cache"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_plain_dirs(self) -> None:
        src = self.tmp / "transcripts"
        make_take(src, "b")
        make_take(src, "a")
        self.assertEqual(names(view_run.discover_takes([src], self.cache)),
                         ["a", "b"])

    def test_tar_gz_per_take_is_unpacked(self) -> None:
        src = self.tmp / "transcripts"
        track = make_take(src, "a")
        with tarfile.open(src / "a.tar.gz", "w:gz") as tar:
            tar.add(track, arcname="a")
        for f in track.iterdir():
            f.unlink()
        track.rmdir()

        takes = view_run.discover_takes([src], self.cache)
        self.assertEqual(names(takes), ["a"])
        self.assertTrue((takes[0][1] / "score.abc").is_file())
        self.assertTrue(takes[0][1].is_relative_to(self.cache))

    def test_zip_with_transcripts_wrapper(self) -> None:
        build = self.tmp / "build"
        tree = build / "transcripts"
        make_take(tree, "p01")
        make_take(tree, "p02")
        archive = self.tmp / "run_abc_transcript.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for path in tree.rglob("*"):
                zf.write(path, path.relative_to(build))

        takes = view_run.discover_takes([archive], self.cache)
        self.assertEqual(names(takes), ["p01", "p02"])
        self.assertTrue(all(t.is_relative_to(self.cache) for _, t in takes))

    def test_expanded_take_wins_over_archive(self) -> None:
        src = self.tmp / "transcripts"
        track = make_take(src, "a")
        with tarfile.open(src / "a.tar.gz", "w:gz") as tar:
            tar.add(track, arcname="a")

        takes = view_run.discover_takes([src], self.cache)
        self.assertEqual(names(takes), ["a"])
        self.assertEqual(takes[0][1], track)
        self.assertFalse(self.cache.exists())

    def test_archive_without_take_is_ignored(self) -> None:
        src = self.tmp / "transcripts"
        src.mkdir()
        with zipfile.ZipFile(src / "karaoke.zip", "w") as zf:
            zf.writestr("p01/player.html", "<html></html>")
        self.assertEqual(view_run.discover_takes([src], self.cache), [])


if __name__ == "__main__":
    unittest.main()
