"""Opt-in host checks for external audio dependencies."""

from __future__ import annotations

import os
import shutil

import pytest

pytestmark = pytest.mark.integration


def test_audio_binaries_are_available_on_host():
    if os.environ.get("RUN_INTEGRATION") != "1":
        pytest.skip("set RUN_INTEGRATION=1 to run host integration checks")

    missing = [name for name in ("audtool", "ffmpeg", "pactl") if shutil.which(name) is None]
    assert not missing, f"missing required audio binaries: {', '.join(missing)}"
