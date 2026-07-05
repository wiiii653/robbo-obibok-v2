"""Remote track download helpers."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import yt_dlp

YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com",
                   "music.youtube.com", "youtube-nocookie.com"}
MAX_YOUTUBE_DURATION_SECONDS = 3600  # 1h max
YOUTUBE_CACHE_TTL_SECONDS = 86400 * 7  # 7 dni cache

logger = logging.getLogger(__name__)

MAX_REMOTE_DOWNLOAD_BYTES = 128 * 1024 * 1024
DEFAULT_REMOTE_TIMEOUT = 30
MAX_MODULE_DOWNLOAD_BYTES = 64 * 1024 * 1024


def is_remote_track(track: str) -> bool:
    return track.startswith("http://") or track.startswith("https://")


def is_youtube_url(url: str) -> bool:
    try:
        domain = urlparse(url).netloc.lower()
        return any(domain == d or domain.endswith("." + d) for d in YOUTUBE_DOMAINS)
    except Exception:
        return False


def youtube_cache_path(root_dir: str, video_id: str, ext: str = "m4a") -> str:
    cache_dir = Path(root_dir) / "var" / "downloads" / "youtube"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir / f"{video_id}.{ext}")


def download_youtube_track(url: str, root_dir: str) -> str | None:
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            vid = info.get("id", "")
            dur = info.get("duration", 0) or 0
            if dur > MAX_YOUTUBE_DURATION_SECONDS:
                logger.warning("YouTube track too long: %ds (max %ds)", dur, MAX_YOUTUBE_DURATION_SECONDS)
                return None
            title = info.get("title", "unknown")
            # Check cache first
            for ext_candidate in ("m4a", "webm", "mp3", "ogg"):
                cached = youtube_cache_path(root_dir, vid, ext_candidate)
                if Path(cached).is_file() and Path(cached).stat().st_size > 0:
                    logger.info("YouTube cache hit: %s (%s)", cached, title)
                    return cached
            # Download best audio
            output_tmpl = str(Path(root_dir) / "var" / "downloads" / "youtube" / f"{vid}.%(ext)s")
            ydl_opts = {
                "format": "bestaudio[ext=m4a]/bestaudio/best",
                "outtmpl": output_tmpl,
                "quiet": True,
                "no_warnings": True,
                "max_filesize": 256 * 1024 * 1024,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl_dl:
                ydl_dl.download([url])
            # Find the downloaded file
            for f in Path(root_dir).glob(f"var/downloads/youtube/{vid}.*"):
                if f.is_file() and f.stat().st_size > 0:
                    logger.info("YouTube downloaded: %s (%s)", f.name, title)
                    return str(f)
            logger.warning("YouTube download finished but file not found for %s", vid)
            return None
    except yt_dlp.DownloadError as exc:
        logger.warning("YouTube download error for %s: %s", url, exc)
        return None
    except Exception as exc:
        logger.warning("Unexpected YouTube error for %s: %s", url, exc)
        return None


def uses_module_cache(url: str) -> bool:
    path = unquote(urlparse(url).path).lower()
    return "modarchive" in url.lower() or "moduleid=" in url.lower() or path.endswith(
        (".mod", ".xm", ".s3m", ".it")
    )


def _sanitize_stem(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in " _-." else "_" for ch in value)
    return safe.strip().strip(".") or "track"


def remote_cache_path(root_dir: str, url: str) -> str:
    parsed = urlparse(url)
    stem = Path(unquote(parsed.path)).stem or "track"
    suffix = Path(unquote(parsed.path)).suffix or ".bin"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    temp_dir = Path(root_dir) / "var" / "downloads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return str(temp_dir / f"{_sanitize_stem(stem)}-{digest}{suffix}")


def _cache_dir(root_dir: str, *parts: str) -> Path:
    path = Path(root_dir) / "var" / "downloads"
    for part in parts:
        path /= part
    path.mkdir(parents=True, exist_ok=True)
    return path


def _download_bytes(url: str, *, max_bytes: int, timeout: int = DEFAULT_REMOTE_TIMEOUT) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"remote track exceeds {max_bytes} bytes: {url}")
    return data


def _valid_cached_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as temp:
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
            temp_path = temp.name
        os.replace(temp_path, path)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def download_remote_track(url: str, output_path: str, *, timeout: int = DEFAULT_REMOTE_TIMEOUT) -> str:
    path = Path(output_path)
    if _valid_cached_file(path):
        return output_path
    data = _download_bytes(url, max_bytes=MAX_REMOTE_DOWNLOAD_BYTES, timeout=timeout)
    _write_atomic(path, data)
    return output_path


def download_modarchive_module(url: str, *, root_dir: str) -> str:
    mod_id = ""
    if "moduleid=" in url:
        mod_id = url.split("moduleid=", 1)[-1].split("&", 1)[0]
    cache_dir = _cache_dir(root_dir, "modarchive")
    if mod_id:
        for cached in cache_dir.iterdir():
            if (cached.name.startswith(f"{mod_id}_") or cached.name == mod_id) and _valid_cached_file(cached):
                return str(cached)
    parsed = urlparse(url)
    stem = Path(unquote(parsed.path)).stem or mod_id or "module"
    suffix = Path(unquote(parsed.path)).suffix or ".mod"
    # ModArchive download URLs end in .php even though the content
    # is always a tracker module (MOD/XM/S3M/IT) — fix the extension
    if suffix.lower() == ".php":
        suffix = ".mod"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    output_path = cache_dir / f"{_sanitize_stem(stem)}-{digest}{suffix}"
    if _valid_cached_file(output_path):
        return str(output_path)
    data = _download_bytes(url, max_bytes=MAX_MODULE_DOWNLOAD_BYTES)
    _write_atomic(output_path, data)
    if mod_id:
        alias = cache_dir / f"{mod_id}_{output_path.name}"
        if not _valid_cached_file(alias):
            _write_atomic(alias, data)
    return str(output_path)
