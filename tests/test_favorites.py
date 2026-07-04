"""Tests for favorites module."""

from __future__ import annotations

import json

from src.favorites import Favorites, PlaylistLibrary


class TestFavorites:
    def test_toggle_add(self, tmp_path):
        favs = Favorites(str(tmp_path))
        assert favs.toggle(1, "test.sap", "Test Song") is True
        assert favs.has_track(1, "test.sap") is True

    def test_toggle_remove(self, tmp_path):
        favs = Favorites(str(tmp_path))
        favs.toggle(1, "test.sap")
        assert favs.toggle(1, "test.sap") is False
        assert favs.has_track(1, "test.sap") is False

    def test_get_tracks(self, tmp_path):
        favs = Favorites(str(tmp_path))
        favs.toggle(1, "a.sap", "Song A")
        favs.toggle(1, "b.sap", "Song B")
        tracks = favs.get_tracks(1)
        assert len(tracks) == 2
        assert tracks[0]["filepath"] == "a.sap"

    def test_count(self, tmp_path):
        favs = Favorites(str(tmp_path))
        assert favs.count(1) == 0
        favs.toggle(1, "a.sap")
        assert favs.count(1) == 1

    def test_has_track(self, tmp_path):
        favs = Favorites(str(tmp_path))
        assert favs.has_track(1, "nope.sap") is False
        favs.toggle(1, "yes.sap")
        assert favs.has_track(1, "yes.sap") is True

    def test_persistence(self, tmp_path):
        favs = Favorites(str(tmp_path))
        favs.toggle(1, "test.sap", "Test")
        favs2 = Favorites(str(tmp_path))
        assert favs2.has_track(1, "test.sap") is True
        assert favs2.count(1) == 1

    def test_ignores_malformed_entries(self, tmp_path):
        path = tmp_path / "favorites.json"
        path.write_text(json.dumps({"1": [{"filepath": "ok.sap"}, {"bad": True}]}))
        favs = Favorites(str(tmp_path))
        tracks = favs.get_tracks(1)
        assert len(tracks) == 1
        assert tracks[0]["filepath"] == "ok.sap"

    def test_user_isolation(self, tmp_path):
        favs = Favorites(str(tmp_path))
        favs.toggle(1, "a.sap")
        favs.toggle(2, "b.sap")
        assert favs.count(1) == 1
        assert favs.count(2) == 1
        assert favs.has_track(1, "b.sap") is False

    def test_same_path_dedup_by_filepath(self, tmp_path):
        favs = Favorites(str(tmp_path))
        assert favs.toggle(1, "song.mod", collection_id="tiny") is True
        # Same filepath from different collection → already favorited, removes it
        assert favs.toggle(1, "song.mod", collection_id="kgen") is False
        assert favs.count(1) == 0
        # Add again — clean slate
        assert favs.add(1, "song.mod", collection_id="tiny") is True
        assert favs.add(1, "song.mod", collection_id="kgen") is False  # duplicate, blocked
        assert favs.count(1) == 1
        assert favs.has_track(1, "song.mod") is True


class TestPlaylistLibrary:
    def test_save_and_load(self, tmp_path):
        lib = PlaylistLibrary(str(tmp_path))
        tracks = [{"filepath": "a.sap", "title": "Song A"}]
        lib.save("My Playlist", tracks, 123, "TestUser")
        loaded = lib.load("My Playlist")
        assert loaded is not None
        assert loaded["name"] == "My Playlist"
        assert loaded["author"] == "TestUser"
        assert len(loaded["tracks"]) == 1

    def test_list_playlists(self, tmp_path):
        lib = PlaylistLibrary(str(tmp_path))
        lib.save("Playlist 1", [{"filepath": "a.sap"}], 1, "User1")
        lib.save("Playlist 2", [{"filepath": "b.sap"}, {"filepath": "c.sap"}], 2, "User2")
        playlists = lib.list_playlists()
        assert len(playlists) == 2
        assert playlists[0]["tracks"] == 1
        assert playlists[1]["tracks"] == 2

    def test_delete(self, tmp_path):
        lib = PlaylistLibrary(str(tmp_path))
        lib.save("To Delete", [], 1, "User")
        assert lib.delete("To Delete") is True
        assert lib.load("To Delete") is None

    def test_delete_nonexistent(self, tmp_path):
        lib = PlaylistLibrary(str(tmp_path))
        assert lib.delete("Nope") is False

    def test_load_nonexistent(self, tmp_path):
        lib = PlaylistLibrary(str(tmp_path))
        assert lib.load("Nope") is None

    def test_load_ignores_malformed_tracks(self, tmp_path):
        lib = PlaylistLibrary(str(tmp_path))
        path = tmp_path / "var" / "playlists" / "My Playlist.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "name": "My Playlist",
            "author": "User",
            "tracks": [{"filepath": "ok.sap"}, {"bad": True}],
        }))
        loaded = lib.load("My Playlist")
        assert loaded is not None
        assert len(loaded["tracks"]) == 1

    def test_safe_name(self, tmp_path):
        lib = PlaylistLibrary(str(tmp_path))
        assert lib._safe_name("My Cool Playlist!") == "My Cool Playlist_"
        assert lib._safe_name("") == "unnamed"
