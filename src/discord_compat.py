"""Optional discord.py compatibility layer for tests and offline tooling."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable


try:  # pragma: no cover - exercised indirectly when discord.py is installed
    import discord as _discord
    from discord.ext import commands as _commands
except ModuleNotFoundError:  # pragma: no cover - covered by local tests
    class _Embed:
        def __init__(self, *, title: str = "", description: str = "", color: int = 0) -> None:
            self.title = title
            self.description = description
            self.color = color
            self.fields: list[dict[str, Any]] = []
            self.footer: dict[str, Any] = {}

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "_Embed":
            embed = cls(
                title=data.get("title", ""),
                description=data.get("description", ""),
                color=data.get("color", 0),
            )
            embed.fields = list(data.get("fields", []))
            embed.footer = dict(data.get("footer", {}))
            return embed

        def add_field(self, *, name: str, value: str, inline: bool = True) -> None:
            self.fields.append({"name": name, "value": value, "inline": inline})

        def set_footer(self, *, text: str = "") -> None:
            self.footer = {"text": text}


    @dataclass
    class _Intents:
        message_content: bool = False
        voice_states: bool = False
        reactions: bool = False
        members: bool = False

        @classmethod
        def default(cls) -> "_Intents":
            return cls()


    class _AudioSource:
        pass


    class _VoiceClient:
        def __init__(self, **attrs: Any) -> None:
            for key, value in attrs.items():
                setattr(self, key, value)

        async def disconnect(self) -> None:
            return None

        def play(self, source: Any, after: Callable[[Exception | None], None] | None = None) -> None:
            self.source = source
            self.after = after


    class _Command:
        def __init__(self, callback: Callable[..., Any], **kwargs: Any) -> None:
            self.callback = callback
            self.name = kwargs.get("name", callback.__name__)
            self.aliases = list(kwargs.get("aliases", []))


    class _Cog:
        @staticmethod
        def listener(name: str | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
            def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
                return func

            return decorator


    class _Bot:
        def __init__(self, *_, **kwargs: Any) -> None:
            self.command_prefix = kwargs.get("command_prefix", "!")
            self.intents = kwargs.get("intents")
            self._cogs: dict[str, Any] = {}
            self.user = None
            self.guilds: list[Any] = []
            self._closed = False

        def remove_command(self, name: str) -> None:
            return None

        async def add_cog(self, cog: Any) -> None:
            self._cogs[cog.__class__.__name__] = cog

        def get_cog(self, name: str) -> Any:
            return self._cogs.get(name)

        async def process_commands(self, message: Any) -> None:
            return None

        async def close(self) -> None:
            self._closed = True

        def is_closed(self) -> bool:
            return self._closed

        def run(self, token: str) -> None:
            raise RuntimeError("discord.py is not installed")


    def _command(**kwargs: Any) -> Callable[[Callable[..., Any]], _Command]:
        def decorator(func: Callable[..., Any]) -> _Command:
            return _Command(func, **kwargs)

        return decorator


    def _get(iterable: Any, /, **attrs: Any) -> Any:
        for item in iterable:
            if all(getattr(item, key, None) == value for key, value in attrs.items()):
                return item
        return None


    _discord = SimpleNamespace(
        Embed=_Embed,
        Intents=_Intents,
        AudioSource=_AudioSource,
        VoiceClient=_VoiceClient,
        Guild=type("Guild", (), {}),
        Message=type("Message", (), {}),
        Member=type("Member", (), {}),
        VoiceState=type("VoiceState", (), {}),
        RawReactionActionEvent=type("RawReactionActionEvent", (), {}),
        utils=SimpleNamespace(get=_get),
    )
    _commands = SimpleNamespace(Bot=_Bot, Cog=_Cog, Context=type("Context", (), {}), command=_command)


discord = _discord
commands = _commands
