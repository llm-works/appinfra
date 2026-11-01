# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/core/app.py that initialize the lifecycle, install signal handlers, or read config
files from disk.
"""

import argparse
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from appinfra.app.core.app import App

# =============================================================================
# Test Main
# =============================================================================


class TestMain:
    """Test main method (lines 252-271)."""

    def test_main_handles_keyboard_interrupt(self):
        """Test main handles KeyboardInterrupt."""
        import time as std_time

        app = App()
        app.lifecycle._logger = Mock()
        app.lifecycle._lifecycle_logger = Mock()
        app.lifecycle._start_time = std_time.monotonic()

        with patch.object(app, "setup", side_effect=KeyboardInterrupt):
            result = app.main()

        assert result == 130  # Standard SIGINT exit code

    def test_main_handles_exception(self):
        """Test main handles exceptions."""
        import time as std_time

        app = App()
        app.lifecycle._logger = Mock()
        app.lifecycle._lifecycle_logger = Mock()
        app.lifecycle._start_time = std_time.monotonic()

        with (
            patch.object(app, "setup", side_effect=ValueError("test error")),
            patch.object(app.lifecycle, "finalize"),
            pytest.raises(ValueError, match="test error"),
        ):
            app.main()

    def test_bare_run_without_tools_reaches_run_no_tool(self):
        """A bare run of an app with no tools ends in run_no_tool, not a crash.

        argparse only creates the ``tool`` dest when subparsers exist, and
        CommandHandler skips them for an empty registry.
        """
        app = App()

        with (
            patch.object(sys, "argv", ["zero-tool-app"]),
            patch("appinfra.app.core.shutdown.signal.signal"),
        ):
            result = app.main()

        assert result == 1

    def test_bare_run_without_tools_uses_run_no_tool_override(self):
        """run_no_tool is the override hook for an app that registers no tools."""

        class NoToolApp(App):
            def run_no_tool(self) -> int:
                return 0

        app = NoToolApp()

        with (
            patch.object(sys, "argv", ["zero-tool-app"]),
            patch("appinfra.app.core.shutdown.signal.signal"),
        ):
            result = app.main()

        assert result == 0


# =============================================================================
# --etc-dir and config spec loading
# =============================================================================


class TestEtcDirResolutionOnOptIn:
    """Verify _resolve_etc_dir_if_opted_in populates _etc_dir from an explicit
    --etc-dir when the standard arg is enabled on an app without a spec."""

    def test_explicit_etc_dir_resolves_and_sets(self, tmp_path):
        custom = tmp_path / "myetc"
        custom.mkdir()

        app = App()
        app._standard_args = {"etc_dir": True}
        app._parsed_args = argparse.Namespace(etc_dir=str(custom))

        app._resolve_etc_dir_if_opted_in()

        assert app.etc_dir == str(custom.resolve())

    def test_explicit_etc_dir_file_raises(self, tmp_path):
        """A path that exists but is not a directory is rejected too."""
        not_a_dir = tmp_path / "file.yaml"
        not_a_dir.write_text("")

        app = App()
        app._standard_args = {"etc_dir": True}
        app._parsed_args = argparse.Namespace(etc_dir=str(not_a_dir))

        with pytest.raises(FileNotFoundError):
            app._resolve_etc_dir_if_opted_in()

    def test_flag_omitted_leaves_none(self, monkeypatch, tmp_path):
        """Without --etc-dir there is no default: _etc_dir stays unset even
        when a ./etc directory exists beside the cwd."""
        (tmp_path / "etc").mkdir()
        monkeypatch.chdir(tmp_path)

        app = App()
        app._standard_args = {"etc_dir": True}
        app._parsed_args = argparse.Namespace(etc_dir=None)

        app._resolve_etc_dir_if_opted_in()

        assert app.etc_dir is None

    def test_not_opted_in_is_noop(self, tmp_path):
        app = App()
        app._standard_args = {"etc_dir": False}
        app._parsed_args = argparse.Namespace(etc_dir=str(tmp_path))

        app._resolve_etc_dir_if_opted_in()

        assert app.etc_dir is None


class TestConfigSpecLoading:
    """`_load_config_spec` runs the v1 protocol precedence chain in App.setup."""

    @pytest.fixture(autouse=True)
    def clear_infra_env_overrides(self, monkeypatch):
        """Clear INFRA_* env vars that CI sets, so minimal test configs don't fail."""
        for var in list(os.environ):
            if var.startswith("INFRA_"):
                monkeypatch.delenv(var, raising=False)

    def _make_bundled_base(self, tmp_path: Path) -> Path:
        base = tmp_path / "pkg" / "etc" / "myapp.yaml"
        base.parent.mkdir(parents=True)
        base.write_text("origin: bundled\napi:\n  port: 8000\n")
        return base

    def _make_spec(self, tmp_path: Path):
        from appinfra.config import ConfigSpec

        return ConfigSpec("myorg", "myapp", path=self._make_bundled_base(tmp_path))

    def test_custom_etc_dir_loads_from_user_path(self, monkeypatch, tmp_path):
        custom = tmp_path / "user_etc"
        custom.mkdir()
        (custom / "myapp.yaml").write_text("origin: user\napi:\n  port: 12345\n")
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=str(custom))

        result = app._load_config_spec()

        assert app.config.origin == "user"
        assert app.config.api.port == 12345
        assert app._etc_dir == str(custom.resolve())
        assert app._config_file == "myapp.yaml"
        assert app._origin == custom.resolve()
        assert result["etc_dir"] == str(custom.resolve())
        assert app.config_spec is spec
        assert app.config_path == custom.resolve() / "myapp.yaml"
        assert app._config_source is not None
        assert app._config_source.rule == 3

    def test_xdg_overlay_loads_when_no_custom(self, monkeypatch, tmp_path):
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        overlay = xdg_home / "myorg" / "myapp.yaml"
        overlay.write_text("origin: overlay\napi:\n  port: 9000\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=None)

        app._load_config_spec()

        assert app.config.origin == "overlay"
        assert app._config_file == "myapp.yaml"
        assert app._origin == spec.base_config.parent.resolve()

    def test_bundled_base_when_no_custom_and_no_overlay(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nonexistent"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "nonexistent-sys"))
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=None)

        app._load_config_spec()

        assert app.config.origin == "bundled"
        assert app._origin == spec.base_config.parent.resolve()

    def test_custom_wins_over_xdg_overlay(self, monkeypatch, tmp_path):
        """Explicit --etc-dir must not be shadowed by an existing overlay."""
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("origin: overlay\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        custom = tmp_path / "user_etc"
        custom.mkdir()
        (custom / "myapp.yaml").write_text("origin: user\n")
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=str(custom))

        app._load_config_spec()

        assert app.config.origin == "user"

    def test_custom_config_absolute_path_wins_over_spec(self, monkeypatch, tmp_path):
        """--config /abs.yaml loads directly, bypasses spec (XDG + base)."""
        xdg_home = tmp_path / "xdg"
        (xdg_home / "myorg").mkdir(parents=True)
        (xdg_home / "myorg" / "myapp.yaml").write_text("origin: overlay\n")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_home))
        monkeypatch.delenv("XDG_CONFIG_DIRS", raising=False)
        target = tmp_path / "elsewhere" / "custom.yaml"
        target.parent.mkdir()
        target.write_text("origin: cli-config\napi:\n  port: 55555\n")
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=None, config=str(target))

        app._load_config_spec()

        assert app.config.origin == "cli-config"
        assert app.config.api.port == 55555
        assert app._origin == target.parent.resolve()

    def test_custom_config_bare_filename_composes_with_etc_dir(
        self, monkeypatch, tmp_path
    ):
        """--etc-dir /foo --config alt.yaml → /foo/alt.yaml."""
        etc = tmp_path / "user_etc"
        etc.mkdir()
        (etc / "alt.yaml").write_text("origin: user-alt\napi:\n  port: 33333\n")
        # An etc/myapp.yaml also exists but must not be picked (--config wins).
        (etc / "myapp.yaml").write_text("origin: user-default\n")
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=str(etc), config="alt.yaml")

        app._load_config_spec()

        assert app.config.origin == "user-alt"
        assert app.config.api.port == 33333

    def test_custom_config_absolute_ignores_etc_dir(self, monkeypatch, tmp_path):
        """--config /abs.yaml with --etc-dir also set → --etc-dir ignored."""
        etc = tmp_path / "user_etc"
        etc.mkdir()
        (etc / "myapp.yaml").write_text("origin: user-default\n")
        target = tmp_path / "elsewhere.yaml"
        target.write_text("origin: cli-absolute\n")
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(etc_dir=str(etc), config=str(target))

        app._load_config_spec()

        assert app.config.origin == "cli-absolute"
        assert app._origin == target.parent.resolve()

    def test_load_and_merge_config_uses_spec(self, monkeypatch, tmp_path):
        """With a spec set, _load_and_merge_config loads the resolved file
        and layers CLI args over it."""
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nonexistent"))
        monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "nonexistent-sys"))
        spec = self._make_spec(tmp_path)

        app = App()
        app._config_spec = spec
        app._parsed_args = argparse.Namespace(
            config=None, etc_dir=None, log_level="debug"
        )

        result = app._load_and_merge_config()

        assert result is not None
        assert app.config.origin == "bundled"
        assert app.config.logging.level == "debug"
        assert app.config_path == spec.base_config

    def test_load_and_merge_config_without_spec_loads_nothing(self, tmp_path):
        """An app without a spec ignores --config and --etc-dir for loading."""
        etc = tmp_path / "etc"
        etc.mkdir()
        (etc / "myapp.yaml").write_text("origin: should-not-load\n")

        app = App()
        app._parsed_args = argparse.Namespace(config="myapp.yaml", etc_dir=str(etc))

        result = app._load_and_merge_config()

        assert result is None
        assert not hasattr(app.config, "origin")
        assert app.config_path is None
