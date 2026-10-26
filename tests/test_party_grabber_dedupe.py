"""Regression tests for grabber file deduplication.

2026-10-26: dedupe_path() compared the size only for the BASE filename and picked
``(2)``, ``(3)``... blindly, so two different tracks that happen to share a size made
every later run add another copy — the collection ended up with
``Keep Running.it``, ``(2)``, ``(3)``, ``(4)``, ``(5)`` at 9.4 MB each (36 MB of junk).
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import party_music_grabber  # noqa: E402


def test_identical_copy_is_a_duplicate(tmp_path):
    dest = tmp_path / "Track.it"
    dest.write_bytes(b"AAA")
    src = tmp_path / "src.it"
    src.write_bytes(b"AAA")

    assert party_music_grabber.dedupe_path(dest, 3, src) == Path()


def test_same_size_different_content_gets_its_own_name(tmp_path):
    dest = tmp_path / "Keep Running.it"
    dest.write_bytes(b"AAA")
    src = tmp_path / "src.it"
    src.write_bytes(b"BBB")

    target = party_music_grabber.dedupe_path(dest, 3, src)

    assert target == tmp_path / "Keep Running (2).it"


def test_duplicate_is_detected_against_suffixed_names_too(tmp_path):
    """Drugi utwor trafia do '(2)'; kolejne pobranie TEGO SAMEGO ma byc duplikatem."""
    dest = tmp_path / "Keep Running.it"
    dest.write_bytes(b"AAA")
    src = tmp_path / "src.it"
    src.write_bytes(b"BBB")

    first = party_music_grabber.dedupe_path(dest, 3, src)
    assert first == tmp_path / "Keep Running (2).it"
    first.write_bytes(b"BBB")

    # ta sama zawartosc co '(2)', ale rozmiar rozny od nazwy bazowej
    again = tmp_path / "again.it"
    again.write_bytes(b"BBB")
    assert party_music_grabber.dedupe_path(dest, 3, again) == Path()


def test_copy_deduped_never_piles_up_copies(tmp_path):
    dest = tmp_path / "Keep Running.it"
    dest.write_bytes(b"AAA")
    src = tmp_path / "src.it"
    src.write_bytes(b"BBB")

    assert party_music_grabber.copy_deduped(src, dest) == tmp_path / "Keep Running (2).it"
    for _ in range(3):
        assert party_music_grabber.copy_deduped(src, dest) == Path()

    assert sorted(p.name for p in tmp_path.glob("Keep Running*")) == [
        "Keep Running (2).it",
        "Keep Running.it",
    ]


def test_copy_deduped_skips_when_base_already_identical(tmp_path):
    dest = tmp_path / "Track.it"
    dest.write_bytes(b"AAA")
    src = tmp_path / "src.it"
    src.write_bytes(b"AAA")

    assert party_music_grabber.copy_deduped(src, dest) == Path()
    assert [p.name for p in tmp_path.glob("Track*")] == ["Track.it"]
