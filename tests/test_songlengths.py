"""Tests for Songlengths.md5 lookups feeding SID timeouts."""

import hashlib
from pathlib import Path

import pytest

from src import songlengths
from src.songlengths import (
    candidate_db_paths,
    custom_db_path,
    lookup_sid_total_time,
    parse_songlength_value,
    record_sid_length,
    reset_cache,
)


@pytest.fixture(autouse=True)
def fresh_db_cache():
    reset_cache()
    yield
    reset_cache()


class TestParseSonglengthValue:
    def test_simple_mm_ss(self):
        assert parse_songlength_value("2:54") == 174

    def test_zero_padding(self):
        assert parse_songlength_value("0:56") == 56

    def test_fractional_seconds_ceiled(self):
        assert parse_songlength_value("1:03.83") == 64

    def test_multi_subsong_values_are_summed(self):
        # Real-world Duck_Hunt-style entry
        assert parse_songlength_value("0:06.709 0:01.053 0:04.02") == 12

    def test_hh_mm_ss(self):
        assert parse_songlength_value("1:02:03") == 3723

    def test_garbage_yields_zero(self):
        assert parse_songlength_value("nonsense") == 0

    def test_empty_yields_zero(self):
        assert parse_songlength_value("") == 0


class TestCandidateDbPaths:
    def test_order_and_members(self, monkeypatch):
        monkeypatch.setenv("ROBBO_SONGLENGTHS_DB", "/custom/db.md5")
        paths = candidate_db_paths("/archive")
        # Override replaces official sources; learned db always rides last.
        assert paths == ["/custom/db.md5", custom_db_path()]

    def test_no_env_no_archive(self, monkeypatch):
        monkeypatch.delenv("ROBBO_SONGLENGTHS_DB", raising=False)
        paths = candidate_db_paths(None)
        assert paths[0] == "/usr/share/sidplayfp/Songlengths.md5"
        assert paths[-1].endswith("var/songlengths_custom.md5")


class TestCustomDbPath:
    def test_defaults_to_repo_root_var(self):
        assert custom_db_path().endswith("/var/songlengths_custom.md5")

    def test_root_dir_override(self, tmp_path):
        assert custom_db_path(str(tmp_path)) == str(tmp_path / "var" / "songlengths_custom.md5")


class TestRecordSidLength:
    @staticmethod
    def _sid(tmp_path: Path, name: str = "mystery.sid") -> Path:
        sid = tmp_path / name
        sid.write_bytes(b"PSID" + b"\x00" * 64)
        return sid

    def test_rejects_non_sid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ROBBO_SONGLENGTHS_DB", str(tmp_path / "x.md5"))
        mod = tmp_path / "tune.mod"
        mod.write_bytes(b"M.K.")
        assert record_sid_length(str(mod), 100) is False

    @pytest.mark.parametrize("seconds", [0, -5, 36001])
    def test_rejects_implausible_durations(self, tmp_path, monkeypatch, seconds):
        monkeypatch.setenv("ROBBO_SONGLENGTHS_DB", str(tmp_path / "x.md5"))
        sid = self._sid(tmp_path)
        assert record_sid_length(str(sid), seconds) is False

    def test_writes_standard_format_entry(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom.md5"
        monkeypatch.setenv("ROBBO_SONGLENGTHS_DB", str(tmp_path / "unused.md5"))
        sid = self._sid(tmp_path)
        digest = hashlib.md5(sid.read_bytes()).hexdigest()
        import src.songlengths as sl

        monkeypatch.setattr(sl, "custom_db_path", lambda root=None: str(custom))
        assert record_sid_length(str(sid), 192) is True
        body = custom.read_text()
        assert f"{digest}=3:12" in body.splitlines()[1] or f"{digest}=3:12" in body
        # And it is immediately findable via lookup (cache was empty).
        reset_cache()
        assert lookup_sid_total_time(str(sid)) == 192

    def test_remeasurement_replaces_entry_and_lookup_wins(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom.md5"
        import src.songlengths as sl

        monkeypatch.setattr(sl, "custom_db_path", lambda root=None: str(custom))
        sid = self._sid(tmp_path)
        digest = hashlib.md5(sid.read_bytes()).hexdigest()

        assert record_sid_length(str(sid), 180) is True
        assert record_sid_length(str(sid), 200) is True
        lines = [ln for ln in custom.read_text().splitlines() if ln.startswith(digest)]
        assert lines == [f"{digest}=3:20"]

        reset_cache()
        assert lookup_sid_total_time(str(sid)) == 200

    def test_merged_db_prefers_last_source_for_same_digest(self, tmp_path, monkeypatch):
        import src.songlengths as sl

        sid = self._sid(tmp_path)
        digest = hashlib.md5(sid.read_bytes()).hexdigest()
        official = tmp_path / "official.md5"
        official.write_text(f"[Database]\n{digest}=2:54\n")
        custom = tmp_path / "custom.md5"
        custom.write_text(f"[Database]\n{digest}=3:12\n")

        monkeypatch.setenv("ROBBO_SONGLENGTHS_DB", str(official))
        monkeypatch.setattr(sl, "custom_db_path", lambda root=None: str(custom))
        reset_cache()
        assert lookup_sid_total_time(str(sid)) == 192


class TestLookupSidTotalTime:
    @staticmethod
    def _make_sid(tmp_path: Path, name: str = "tune.sid", filler: bytes = b"\x00") -> Path:
        sid = tmp_path / name
        sid.write_bytes(b"PSID" + filler * 120)
        return sid

    @staticmethod
    def _db_for(tmp_path: Path, sid: Path, value: str) -> Path:
        digest = hashlib.md5(sid.read_bytes()).hexdigest()
        db = tmp_path / "Songlengths.md5"
        db.write_text(f"[Database]\r\n{digest}={value}\r\n")
        return db

    def test_single_song_lookup(self, tmp_path):
        sid = self._make_sid(tmp_path)
        db = self._db_for(tmp_path, sid, "2:54")
        assert lookup_sid_total_time(str(sid), db_path=str(db)) == 174

    def test_multi_subsong_sums_all_entries(self, tmp_path):
        sid = self._make_sid(tmp_path)
        db = self._db_for(tmp_path, sid, "0:06.709 0:01.053 0:04.02")
        assert lookup_sid_total_time(str(sid), db_path=str(db)) == 12

    def test_unknown_digest_returns_none(self, tmp_path):
        sid = self._make_sid(tmp_path)
        other = self._make_sid(tmp_path, "other.sid", filler=b"\x01")
        db = self._db_for(tmp_path, other, "2:54")
        assert lookup_sid_total_time(str(sid), db_path=str(db)) is None

    def test_non_sid_extension_returns_none(self, tmp_path):
        mod = tmp_path / "tune.mod"
        mod.write_bytes(b"M.K.")
        db = tmp_path / "Songlengths.md5"
        db.write_text("[Database]\n")
        assert lookup_sid_total_time(str(mod), db_path=str(db)) is None

    def test_missing_file_returns_none(self, tmp_path):
        db = tmp_path / "Songlengths.md5"
        db.write_text("[Database]\n")
        missing = tmp_path / "ghost.sid"
        assert lookup_sid_total_time(str(missing), db_path=str(db)) is None

    def test_db_loaded_once_then_reused_from_cache(self, tmp_path, monkeypatch):
        sid = self._make_sid(tmp_path)
        db = self._db_for(tmp_path, sid, "1:30")
        monkeypatch.setenv("ROBBO_SONGLENGTHS_DB", str(db))
        # Keep the learned db out of the picture (isolated tmp path).
        monkeypatch.setattr(
            songlengths,
            "custom_db_path",
            lambda root=None: str(tmp_path / "custom.md5"),
        )
        # First call loads the DB into the module cache...
        assert lookup_sid_total_time(str(sid)) == 90
        # ...second call must hit the cache (no db_path argument).
        assert songlengths.loaded_db_path() == str(db)
        assert lookup_sid_total_time(str(sid)) == 90

    def test_empty_db_returns_none_without_crash(self, tmp_path, monkeypatch):
        sid = self._make_sid(tmp_path)
        empty = tmp_path / "empty.md5"
        empty.write_text("")
        monkeypatch.setenv("ROBBO_SONGLENGTHS_DB", str(empty))
        assert lookup_sid_total_time(str(sid)) is None
