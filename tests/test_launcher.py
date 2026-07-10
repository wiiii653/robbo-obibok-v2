"""Tests for launcher module."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from src.config import AppConfig
from src.launcher import create_bot, load_dotenv, remove_pid, write_pid


class TestLoadDotenv:
    def test_loads_env_file(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("TEST_KEY=test_value\n")
        load_dotenv(str(tmp_path))
        assert os.environ.get("TEST_KEY") == "test_value"

    def test_ignores_comments(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("# COMMENT\nKEY=value\n")
        load_dotenv(str(tmp_path))
        assert os.environ.get("KEY") == "value"

    def test_nonexistent(self, tmp_path):
        load_dotenv(str(tmp_path))
        assert os.environ.get("NONEXISTENT") is None


class TestPidManagement:
    def test_write_and_remove_pid(self):
        write_pid()
        pid_path = Path(__file__).resolve().parent.parent / "obibok.pid"
        assert pid_path.exists()
        assert pid_path.read_text() == str(os.getpid())

        remove_pid()
        assert not pid_path.exists()

    def test_remove_pid_nonexistent(self):
        pid_path = Path(__file__).resolve().parent.parent / "obibok.pid"
        if pid_path.exists():
            pid_path.unlink()
        remove_pid()


class TestCreateBot:
    def test_create_bot(self, tmp_path):
        config = AppConfig()
        config.token = "test-token"
        bot = create_bot(config)
        assert bot is not None
        assert bot.engine is not None
        assert bot.monitor is not None


class TestSetupLogging:
    def test_setup_logging_runs(self):
        from src.launcher import setup_logging

        setup_logging()
        assert True

    @patch("src.launcher.sys.exit")
    @patch("src.launcher.load_dotenv")
    @patch("src.launcher.load_config")
    def test_main_no_token_exits(self, mock_config, mock_dotenv, mock_exit):
        mock_config.return_value = AppConfig()
        mock_exit.side_effect = SystemExit
        from src.launcher import main

        try:
            main()
        except SystemExit:
            pass
        mock_exit.assert_called_once_with(1)

    @patch("src.launcher.sys.exit")
    @patch("src.launcher.check_audacious_version")
    @patch("src.launcher.load_dotenv")
    @patch("src.launcher.load_config")
    def test_main_rejects_unsupported_audacious(
        self, mock_config, mock_dotenv, mock_check, mock_exit
    ):
        config = AppConfig()
        config.token = "test-token"
        mock_config.return_value = config
        mock_check.side_effect = RuntimeError("Unsupported Audacious version 4.6.2; expected 4.6.1")
        mock_exit.side_effect = SystemExit
        from src.launcher import main

        try:
            main()
        except SystemExit:
            pass
        mock_exit.assert_called_once_with(1)
