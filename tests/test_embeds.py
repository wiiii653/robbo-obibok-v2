"""Tests for embeds module."""

from __future__ import annotations

from src.embeds import now_playing_embed, queue_embed, status_embed


class TestNowPlayingEmbed:
    def test_basic(self):
        embed = now_playing_embed("Test Track", "Author", "ASMA", "🟢", 5, 100)
        assert embed["title"] == "🟢 Now Playing"
        assert "**Test Track**" in embed["description"]
        assert "by Author" in embed["description"]
        assert embed["fields"][0]["value"] == "ASMA"
        assert embed["fields"][1]["value"] == "5/100"

    def test_no_author(self):
        embed = now_playing_embed("Track", "", "HVSC", "🟣", 1, 10)
        assert "by" not in embed["description"]
        assert "**Track**" in embed["description"]

    def test_custom_color(self):
        embed = now_playing_embed("T", "A", "C", "?", 1, 1, color=0xFF0000)
        assert embed["color"] == 0xFF0000

    def test_default_color(self):
        embed = now_playing_embed("T", "A", "C", "?", 1, 1)
        assert embed["color"] == 0x00FF00


class TestQueueEmbed:
    def test_basic(self):
        queue = [
            {"index": 0, "path": "a.sap", "filename": "a.sap", "is_current": True},
            {"index": 1, "path": "b.sap", "filename": "b.sap", "is_current": False},
        ]
        embed = queue_embed(queue, 0)
        assert embed["title"] == "Queue"
        assert "a.sap" in embed["description"]
        assert "b.sap" in embed["description"]
        assert "▶" in embed["description"]
        assert "2 tracks" in embed["footer"]["text"]

    def test_empty_queue(self):
        embed = queue_embed([], 0)
        assert "empty" in embed["description"].lower()

    def test_pagination(self):
        queue = [
            {"index": i, "path": f"t{i}.sap", "filename": f"t{i}.sap", "is_current": False}
            for i in range(25)
        ]
        embed = queue_embed(queue, 0, page=0, per_page=10)
        assert "Page 1/3" in embed["footer"]["text"]

    def test_page_2(self):
        queue = [
            {"index": i, "path": f"t{i}.sap", "filename": f"t{i}.sap", "is_current": False}
            for i in range(15)
        ]
        embed = queue_embed(queue, 10, page=1, per_page=10)
        assert "Page 2/2" in embed["footer"]["text"]


class TestStatusEmbed:
    def test_playing(self):
        embed = status_embed("ASMA", "🟢", 6300, True, "test.sap")
        assert embed["title"] == "🟢 ASMA"
        assert embed["color"] == 0x2ECC71
        assert "Playing" in embed["fields"][0]["value"]
        assert "6300" in embed["fields"][1]["value"]
        assert "test.sap" in embed["description"]

    def test_stopped(self):
        embed = status_embed("HVSC", "🟣", 60000, False)
        assert embed["color"] == 0x95A5A6
        assert "Stopped" in embed["fields"][0]["value"]

    def test_no_current_track(self):
        embed = status_embed("C", "?", 0, True)
        assert embed["description"] == ""
