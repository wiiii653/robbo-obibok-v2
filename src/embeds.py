"""Discord rich embed builders."""

from __future__ import annotations


def now_playing_embed(
    title: str,
    author: str,
    collection_name: str,
    collection_icon: str,
    position: int,
    total: int,
    color: int = 0x00FF00,
) -> dict:
    return {
        "title": f"{collection_icon} Now Playing",
        "description": f"**{title}**\nby {author}" if author else f"**{title}**",
        "color": color,
        "fields": [
            {"name": "Collection", "value": collection_name, "inline": True},
            {"name": "Position", "value": f"{position}/{total}", "inline": True},
        ],
    }


def queue_embed(
    queue: list[dict],
    position: int,
    page: int = 0,
    per_page: int = 10,
) -> dict:
    start = page * per_page
    end = start + per_page
    items = queue[start:end]

    lines: list[str] = []
    for item in items:
        marker = "▶" if item.get("is_current") else " "
        lines.append(f"`{item['index'] + 1}.` {marker} `{item['filename']}`")

    total_pages = max(1, (len(queue) + per_page - 1) // per_page)
    return {
        "title": "Queue",
        "description": "\n".join(lines) if lines else "Queue empty",
        "color": 0x3498DB,
        "footer": {"text": f"Page {page + 1}/{total_pages} • {len(queue)} tracks"},
    }


def status_embed(
    collection_name: str,
    collection_icon: str,
    track_count: int,
    is_playing: bool,
    current_track: str = "",
) -> dict:
    return {
        "title": f"{collection_icon} {collection_name}",
        "color": 0x2ECC71 if is_playing else 0x95A5A6,
        "fields": [
            {"name": "Status", "value": "Playing" if is_playing else "Stopped", "inline": True},
            {"name": "Tracks", "value": str(track_count), "inline": True},
        ],
        "description": f"Now playing: `{current_track}`" if current_track else "",
    }
