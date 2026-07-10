"""Remote track download helpers."""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import socket
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import yt_dlp

YOUTUBE_DOMAINS = {
    "youtube.com",
    "www.youtube.com",
    "youtu.be",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
}
MAX_YOUTUBE_DURATION_SECONDS = 3600  # 1h max
YOUTUBE_CACHE_TTL_SECONDS = 86400 * 7  # 7 dni cache

logger = logging.getLogger(__name__)

MAX_REMOTE_DOWNLOAD_BYTES = 128 * 1024 * 1024
DEFAULT_REMOTE_TIMEOUT = 30
REMOTE_DOWNLOAD_ATTEMPTS = 3
REMOTE_RETRY_DELAY_SECONDS = 1.0
MAX_MODULE_DOWNLOAD_BYTES = 64 * 1024 * 1024


def _normalized_domains(domains: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    return tuple(domain.strip().lower().lstrip(".") for domain in (domains or ()) if domain.strip())


def _host_matches_allowlist(hostname: str, allowed_domains: tuple[str, ...]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains)


def _is_public_hostname(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addresses = {
                result[4][0]
                for result in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
            }
        except OSError:
            return False
        return all(_is_public_hostname(address) for address in addresses)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def is_allowed_remote_url(
    url: str,
    allowed_domains: tuple[str, ...] | list[str] | None = None,
) -> bool:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not hostname:
            return False
        allowed = _normalized_domains(allowed_domains)
        if allowed and not _host_matches_allowlist(hostname.lower(), allowed):
            return False
        if _is_public_hostname(hostname):
            return True
        # Hostname DNS resolution is intentionally skipped when no allowlist
        # is configured to preserve offline/test behavior for arbitrary URLs.
        return not allowed and not _looks_like_private_literal(hostname)
    except ValueError:
        return False


def _looks_like_private_literal(hostname: str) -> bool:
    try:
        return not _is_public_ip(ipaddress.ip_address(hostname))
    except ValueError:
        return False


def _is_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def is_remote_track(track: str) -> bool:
    try:
        parsed = urlparse(track)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


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


def download_youtube_track(
    url: str,
    root_dir: str,
    *,
    allowed_domains: tuple[str, ...] | list[str] | None = None,
) -> str | None:
    try:
        if not is_allowed_remote_url(url, allowed_domains):
            logger.warning("YouTube URL rejected by policy: %s", url)
            return None
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
            vid = info.get("id", "")
            dur = info.get("duration", 0) or 0
            if info.get("is_live") or info.get("was_live"):
                logger.warning("YouTube livestream not supported: %s (%s)", url, info.get("title", "?"))
                return None
            if dur > MAX_YOUTUBE_DURATION_SECONDS:
                logger.warning(
                    "YouTube track too long: %ds (max %ds)", dur, MAX_YOUTUBE_DURATION_SECONDS
                )
                return None
            title = info.get("title", "unknown")
            # Check cache first
            for ext_candidate in ("m4a", "webm", "mp3", "ogg"):
                cached = youtube_cache_path(root_dir, vid, ext_candidate)
                cached_path = Path(cached)
                if cached_path.is_file() and cached_path.stat().st_size > 0:
                    age = max(0, time.time() - cached_path.stat().st_mtime)
                    if age <= YOUTUBE_CACHE_TTL_SECONDS:
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
                "socket_timeout": 30,
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
    return (
        "modarchive" in url.lower()
        or "moduleid=" in url.lower()
        or path.endswith((".mod", ".xm", ".s3m", ".it"))
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


def _download_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: int = DEFAULT_REMOTE_TIMEOUT,
    allowed_domains: tuple[str, ...] | list[str] | None = None,
) -> bytes:
    if not is_allowed_remote_url(url, allowed_domains):
        raise ValueError(f"remote URL rejected by policy: {url}")

    allowed = _normalized_domains(allowed_domains)

    class SafeRedirectHandler(HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, new_url):
            resolved_url = urljoin(request.full_url, new_url)
            if not is_allowed_remote_url(resolved_url, allowed):
                raise ValueError(f"redirect rejected by policy: {resolved_url}")
            return super().redirect_request(request, fp, code, msg, headers, resolved_url)

    for attempt in range(1, REMOTE_DOWNLOAD_ATTEMPTS + 1):
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            opener = build_opener(SafeRedirectHandler) if allowed else None
            response_context = (
                opener.open(request, timeout=timeout)
                if opener
                else urlopen(request, timeout=timeout)
            )
            with response_context as response:
                headers = getattr(response, "headers", {})
                content_length = headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise ValueError(f"remote track exceeds {max_bytes} bytes: {url}")
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(min(1024 * 1024, max_bytes - total + 1))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"remote track exceeds {max_bytes} bytes: {url}")
            return b"".join(chunks)
        except (OSError, URLError, TimeoutError) as exc:
            if attempt == REMOTE_DOWNLOAD_ATTEMPTS:
                raise
            delay = REMOTE_RETRY_DELAY_SECONDS * 2 ** (attempt - 1)
            logger.warning(
                "Remote download attempt %d/%d failed for %s: %s; retrying in %.1fs",
                attempt,
                REMOTE_DOWNLOAD_ATTEMPTS,
                url,
                exc,
                delay,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


def _valid_cached_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temp:
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
            temp_path = temp.name
        os.replace(temp_path, path)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def download_remote_track(
    url: str,
    output_path: str,
    *,
    timeout: int = DEFAULT_REMOTE_TIMEOUT,
    allowed_domains: tuple[str, ...] | list[str] | None = None,
) -> str:
    path = Path(output_path)
    if _valid_cached_file(path):
        return output_path
    data = _download_bytes(
        url,
        max_bytes=MAX_REMOTE_DOWNLOAD_BYTES,
        timeout=timeout,
        allowed_domains=allowed_domains,
    )
    _write_atomic(path, data)
    return output_path


def download_modarchive_module(
    url: str,
    *,
    root_dir: str,
    allowed_domains: tuple[str, ...] | list[str] | None = None,
) -> str:
    mod_id = ""
    if "moduleid=" in url:
        mod_id = url.split("moduleid=", 1)[-1].split("&", 1)[0]
    cache_dir = _cache_dir(root_dir, "modarchive")
    if mod_id:
        for cached in cache_dir.iterdir():
            if (
                cached.name.startswith(f"{mod_id}_") or cached.name == mod_id
            ) and _valid_cached_file(cached):
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
    data = _download_bytes(
        url,
        max_bytes=MAX_MODULE_DOWNLOAD_BYTES,
        allowed_domains=allowed_domains,
    )
    _write_atomic(output_path, data)
    if mod_id:
        alias = cache_dir / f"{mod_id}_{output_path.name}"
        if not _valid_cached_file(alias):
            _write_atomic(alias, data)
    return str(output_path)
