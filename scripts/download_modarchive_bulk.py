#!/usr/bin/env python3
"""ModArchive bulk downloader — downloads all zipfiles from textfiles.com mirror.

Usage:
    python download_modarchive_bulk.py

Downloads all 36 (0-9, A-Z) snapshot directories and yearly additions.
Uses parallel connections for speed.
"""

import asyncio
import logging
import os
import zipfile
from pathlib import Path

import aiohttp
from index_config import is_junk_path, load_archive_root, remove_junk_paths

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("modarchive-dl")

BASE = "http://modarchive.textfiles.com"
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.environ.get(
    "MODARCHIVE_BULK_OUTDIR",
    str(load_archive_root(Path(_SCRIPT_DIR).parent) / "modarchive"),
)
CONCURRENT = 8  # downloads at a time
TRACK_EXTENSIONS = {".mod", ".xm", ".it", ".s3m"}
MAX_ARCHIVE_MEMBERS = 500
MAX_ARCHIVE_UNPACKED_BYTES = 2 * 1024 * 1024 * 1024

# Directories to download (from the main page)
SNAPSHOT_DIRS = [chr(i) for i in range(ord("0"), ord("9") + 1)] + [
    chr(i) for i in range(ord("A"), ord("Z") + 1)
]

# Yearly additions directories
ADDITIONS_DIRS = [
    "modarchive_2007_official_snapshot_addendum1",
    "modarchive_2008_additions",
    "modarchive_2009_additions",
    "modarchive_2010_additions",
    "modarchive_2011_additions",
    "modarchive_2012_additions",
    "modarchive_2013_additions",
    "modarchive_2014_additions",
    "modarchive_2015_additions",
    "modarchive_2016_additions",
    "modarchive_2017_additions",
    "modarchive_2018_additions",
    "modarchive_2019_additions",
    "modarchive_2020_additions",
    "modarchive_2021_additions",
    "modarchive_2022_additions",
    "modarchive_2023_additions",
]

semaphore = asyncio.Semaphore(CONCURRENT)


def is_safe_download_name(name, extensions):
    """Accept only plain, non-junk filenames with an expected extension."""
    path = Path(name)
    return path.name == name and not is_junk_path(path) and path.suffix.lower() in extensions


def _is_safe_archive_member(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return bool(name) and not name.startswith(("/", "\\")) and ".." not in parts


def extract_zip(zip_path: Path) -> bool:
    """Safely unpack a downloaded ZIP beside itself and remove the archive."""
    destination = zip_path.with_suffix("")
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = archive.infolist()
            files = [info for info in infos if not info.is_dir()]
            total_size = sum(info.file_size for info in files)
            if (
                len(files) > MAX_ARCHIVE_MEMBERS
                or total_size > MAX_ARCHIVE_UNPACKED_BYTES
                or any(
                    info.file_size < 0 or not _is_safe_archive_member(info.filename)
                    for info in infos
                )
            ):
                log.warning("Refusing unsafe ZIP archive %s", zip_path)
                return False
            destination.mkdir(parents=True, exist_ok=True)
            archive.extractall(destination)
    except (OSError, zipfile.BadZipFile) as exc:
        log.warning("Could not extract %s: %s", zip_path, exc)
        return False

    removed = remove_junk_paths(destination)
    zip_path.unlink(missing_ok=True)
    log.info("Extracted %s%s", zip_path.name, f"; removed {removed} junk paths" if removed else "")
    return True


async def fetch_url(session, url):
    """Fetch a URL and return text content."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                return await resp.text()
    except Exception as e:
        log.warning("Failed to fetch %s: %s", url, e)
    return None


async def download_file(session, url, dest_path):
    """Download a file with progress."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    if os.path.exists(dest_path):
        size = os.path.getsize(dest_path)
        if size > 1024:  # assume complete if > 1KB
            return extract_zip(Path(dest_path)) if dest_path.lower().endswith(".zip") else True
    try:
        async with semaphore:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                if resp.status != 200:
                    return False
                data = await resp.read()
                if not data:
                    log.warning("Empty download %s", url)
                    return False
                with open(dest_path, "wb") as f:
                    f.write(data)
                log.info("Downloaded %s (%d bytes)", os.path.basename(dest_path), len(data))
                return extract_zip(Path(dest_path)) if dest_path.lower().endswith(".zip") else True
    except Exception as e:
        log.warning("Download failed %s: %s", url, e)
        return False


async def download_snapshot_dir(session, letter):
    """Download all zip files in a snapshot subdirectory (e.g., 0/, A/)."""
    url = f"{BASE}/modarchive_2007_official_snapshot_120000_modules/{letter}/"
    html = await fetch_url(session, url)
    if not html:
        log.warning("No index for %s/", letter)
        return

    import re

    zip_files = [
        name
        for name in re.findall(r'href="([^"]+\.zip)"', html, flags=re.IGNORECASE)
        if is_safe_download_name(name, {".zip"})
    ]
    if not zip_files:
        log.info("No zips in %s/", letter)
        return

    tasks = []
    for zf in zip_files:
        dl_url = f"{BASE}/modarchive_2007_official_snapshot_120000_modules/{letter}/{zf}"
        dest = os.path.join(OUTDIR, "modarchive_2007_official_snapshot_120000_modules", letter, zf)
        tasks.append(download_file(session, dl_url, dest))

    results = await asyncio.gather(*tasks)
    success = sum(1 for r in results if r)
    log.info("[%s/] %d/%d zips downloaded", letter, success, len(zip_files))


async def download_additions_dir(session, dirname):
    """Download all files in a yearly additions directory."""
    url = f"{BASE}/{dirname}/"
    html = await fetch_url(session, url)
    if not html:
        log.warning("No index for %s", dirname)
        return

    import re

    # Find subdirectories (format dirs like MOD/, XM/, S3M/, etc.)
    subdirs = re.findall(r'href="([A-Z0-9]+)/"', html)
    if not subdirs:
        # Maybe it has zip files directly (like addendum1)
        zip_files = [
            name
            for name in re.findall(r'href="([^"]+\.zip)"', html, flags=re.IGNORECASE)
            if is_safe_download_name(name, {".zip"})
        ]
        if zip_files:
            tasks = []
            for zf in zip_files:
                dl_url = f"{BASE}/{dirname}/{zf}"
                dest = os.path.join(OUTDIR, dirname, zf)
                tasks.append(download_file(session, dl_url, dest))
            results = await asyncio.gather(*tasks)
            success = sum(1 for r in results if r)
            log.info("[%s] %d/%d files downloaded", dirname, success, len(zip_files))
        return

    # Download files in each format subdirectory
    for subdir in subdirs:
        sub_url = f"{BASE}/{dirname}/{subdir}/"
        sub_html = await fetch_url(session, sub_url)
        if not sub_html:
            continue
        files = re.findall(r'href="([^"]+)"', sub_html)
        files = [f for f in files if is_safe_download_name(f, TRACK_EXTENSIONS)]
        if not files:
            continue
        tasks = []
        for fname in files:
            dl_url = f"{BASE}/{dirname}/{subdir}/{fname}"
            dest = os.path.join(OUTDIR, dirname, subdir, fname)
            tasks.append(download_file(session, dl_url, dest))
        results = await asyncio.gather(*tasks)
        success = sum(1 for r in results if r)
        log.info("[%s/%s] %d/%d files", dirname, subdir, success, len(files))


async def main():
    connector = aiohttp.TCPConnector(limit=10, limit_per_host=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        # 1. Main snapshot (36 subdirs, 0-9 + A-Z)
        log.info("=== Starting main snapshot download (36 dirs) ===")
        for letter in SNAPSHOT_DIRS:
            await download_snapshot_dir(session, letter)

        # 2. Yearly additions
        log.info("=== Starting yearly additions ===")
        for d in ADDITIONS_DIRS:
            await download_additions_dir(session, d)

        # 3. Standalone zips
        standalone = ["kiarchive.zip", "woolyss-chiptune-samples.zip"]
        for zf in standalone:
            dl_url = f"{BASE}/{zf}"
            dest = os.path.join(OUTDIR, zf)
            await download_file(session, dl_url, dest)

    log.info("=== ALL DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
