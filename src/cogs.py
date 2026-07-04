"""Compatibility facade for Discord command cogs."""

from .collection_cog import CollectionCog
from .favorites_cog import FavoritesCog
from .playback_cog import PlaybackCog
from .tools_cog import ToolsCog

__all__ = ["PlaybackCog", "CollectionCog", "FavoritesCog", "ToolsCog"]
