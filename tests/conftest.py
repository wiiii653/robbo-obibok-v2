"""Test helpers for async test support."""

from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from pathlib import Path

import pytest


def _plain_temp_root() -> None:
    """Point the temp root at a directory without dot-prefixed components.

    ``index_config.is_junk_path()`` rejects any path containing a dot-prefixed
    component, and pytest derives ``tmp_path`` from ``TMPDIR``. With a dotted
    temp directory (``~/.hermes/cache/scratch``, ``~/.cache/...``) four tests
    fail for reasons that have nothing to do with the code under test. Fix the
    environment once, here, instead of asking every caller to export TMPDIR.
    """
    root = Path(tempfile.gettempdir())
    if not any(part.startswith(".") for part in root.parts[1:]):
        return
    for candidate in ("/tmp", "/var/tmp"):
        if Path(candidate).is_dir() and os.access(candidate, os.W_OK):
            tempfile.tempdir = candidate
            return
    tempfile.tempdir = tempfile.mkdtemp(prefix="pytest-")


_plain_temp_root()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "asyncio: run test function in an event loop")


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    if pyfuncitem.config.pluginmanager.hasplugin("asyncio"):
        return None
    if "asyncio" not in pyfuncitem.keywords:
        return None

    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None

    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
        if name in pyfuncitem.funcargs
    }
    asyncio.run(test_func(**kwargs))
    return True
