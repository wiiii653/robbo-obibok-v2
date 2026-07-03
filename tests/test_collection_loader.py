"""Tests for collections module."""

from __future__ import annotations

import json

from src.collection_loader import (
    extract_metadata,
    flip_collection,
    get_collection,
    load_index,
    load_raw_paths,
    parse_sap_header,
)
from src.models import COLLECTIONS, FLIP_ORDER


class TestCollectionRegistry:
    def test_all_collections_registered(self):
        assert len(COLLECTIONS) == 7
        for col_id in FLIP_ORDER:
            assert col_id in COLLECTIONS

    def test_collection_fields(self):
        for col_id, col in COLLECTIONS.items():
            assert col.id == col_id
            assert col.name
            assert col.extensions
            assert col.cache_file
            assert col.flip_tag

    def test_get_collection(self):
        hvsc = get_collection("hvsc")
        assert hvsc is not None
        assert hvsc.name == "C64 SID (HVSC)"
        assert hvsc.volume == 120

    def test_get_nonexistent_collection(self):
        assert get_collection("nonexistent") is None


class TestFlipCollection:
    def test_flip_cycle(self):
        current = "asma"
        for _ in range(len(FLIP_ORDER)):
            current = flip_collection(current)
        assert current == "asma"

    def test_flip_from_unknown(self):
        assert flip_collection("unknown") == FLIP_ORDER[0]

    def test_flip_order(self):
        assert flip_collection("hvsc") == "asma"
        assert flip_collection("asma") == "modarchive"
        assert flip_collection("kgen") == "hvsc"


class TestLoadIndex:
    def test_load_from_cache(self, tmp_path):
        cache = {
            "version": 1,
            "total": 2,
            "tracks": [
                {"path": "Games/test.sap", "size": 1024},
                {"path": "Composers/author.sid", "size": 2048},
            ],
        }
        cache_file = tmp_path / "test_cache_local.json"
        cache_file.write_text(json.dumps(cache))

        col = COLLECTIONS["asma"]
        original_cache = col.cache_file
        col.cache_file = str(cache_file)
        try:
            tracks = load_index("asma", str(tmp_path))
            assert tracks is not None
            assert len(tracks) == 2
            assert tracks[0].filepath == "Games/test.sap"
            assert tracks[0].collection_id == "asma"
        finally:
            col.cache_file = original_cache

    def test_load_nonexistent_cache(self, tmp_path):
        tracks = load_index("asma", str(tmp_path))
        assert tracks is None

    def test_load_invalid_collection(self):
        assert load_index("nonexistent") is None


class TestLoadRawPaths:
    def test_load_raw_paths(self, tmp_path):
        cache = {"tracks": [{"path": "a.mod"}, {"path": "b.xm"}]}
        cache_file = tmp_path / "test_cache.json"
        cache_file.write_text(json.dumps(cache))

        col = COLLECTIONS["tiny"]
        original_cache = col.cache_file
        col.cache_file = str(cache_file)
        try:
            paths = load_raw_paths("tiny", str(tmp_path))
            assert paths == ["a.mod", "b.xm"]
        finally:
            col.cache_file = original_cache


class TestMetadataExtraction:
    def test_parse_sap_header(self, tmp_path):
        sap_content = b"SAP\n;AUTHOR Test Author\n;NAME Test Song\n;COPYRIGHT 2024\n"
        sap_file = tmp_path / "test.sap"
        sap_file.write_bytes(sap_content)
        meta = parse_sap_header(str(sap_file))
        assert meta.get("AUTHOR") == "Test Author"
        assert meta.get("NAME") == "Test Song"

    def test_parse_sap_nonexistent(self):
        meta = parse_sap_header("/nonexistent/file.sap")
        assert meta == {}

    def test_extract_metadata_sap(self, tmp_path):
        sap_content = b"SAP\n;AUTHOR Composer\n;NAME Track Name\n"
        sap_file = tmp_path / "track.sap"
        sap_file.write_bytes(sap_content)
        meta = extract_metadata(str(sap_file), "asma")
        assert meta.get("AUTHOR") == "Composer"

    def test_extract_metadata_unknown_format(self):
        meta = extract_metadata("/some/file.txt", "asma")
        assert meta == {}
