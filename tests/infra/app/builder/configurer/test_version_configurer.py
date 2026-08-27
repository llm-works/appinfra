# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.app.builder.configurer.version module."""

import logging
from datetime import datetime
from unittest.mock import MagicMock, Mock

import pytest

pytestmark = pytest.mark.unit

from appinfra.app.builder.configurer.version import (
    VersionConfigurer,
    _format_modified,
    _log_build_info,
    _log_package_info,
)


class TestFormatModified:
    """Tests for _format_modified helper."""

    def test_none_returns_na(self):
        """Test None returns 'n/a'."""
        assert _format_modified(None) == "n/a"

    def test_true_returns_true_string(self):
        """Test True returns 'True'."""
        assert _format_modified(True) == "True"

    def test_false_returns_false_string(self):
        """Test False returns 'False'."""
        assert _format_modified(False) == "False"


class TestLogBuildInfo:
    """Tests for _log_build_info helper."""

    def test_log_unmodified_build(self):
        """Test logging unmodified build uses debug."""
        lg = MagicMock(spec=logging.Logger)
        build_info = Mock()
        build_info.modified = False
        build_info.commit = "abc123"
        build_info.message = None
        build_info.build_time = None

        _log_build_info(lg, build_info)

        lg.debug.assert_called_once()
        assert "build info" in lg.debug.call_args[0]

    def test_log_modified_build(self):
        """Test logging modified build uses warning."""
        lg = MagicMock(spec=logging.Logger)
        build_info = Mock()
        build_info.modified = True
        build_info.commit = "abc123"
        build_info.message = None
        build_info.build_time = None

        _log_build_info(lg, build_info)

        lg.warning.assert_called_once()

    def test_log_with_message(self):
        """Test logging includes commit message when present."""
        lg = MagicMock(spec=logging.Logger)
        build_info = Mock()
        build_info.modified = False
        build_info.commit = "abc123"
        build_info.message = "feat: add feature"
        build_info.message_short = "feat: add feature"
        build_info.build_time = None

        _log_build_info(lg, build_info)

        extra = lg.debug.call_args[1]["extra"]
        assert extra["commit_msg"] == "feat: add feature"

    def test_log_with_build_time(self):
        """Test logging includes timestamp when present."""
        lg = MagicMock(spec=logging.Logger)
        build_info = Mock()
        build_info.modified = False
        build_info.commit = "abc123"
        build_info.message = None
        build_info.build_time = datetime(2025, 12, 1, 10, 30, 0)

        _log_build_info(lg, build_info)

        extra = lg.debug.call_args[1]["extra"]
        assert extra["timestamp"] == "2025-12-01 10:30:00"


class TestLogPackageInfo:
    """Tests for _log_package_info helper."""

    def test_log_unmodified_package(self):
        """Test logging unmodified package uses debug."""
        lg = MagicMock(spec=logging.Logger)
        info = Mock()
        info.modified = False
        info.name = "mypackage"
        info.commit = "def456"
        info.message = None
        info.build_time = None

        _log_package_info(lg, info)

        lg.debug.assert_called_once()
        extra = lg.debug.call_args[1]["extra"]
        assert extra["package"] == "mypackage"
        assert extra["commit"] == "def456"

    def test_log_modified_package(self):
        """Test logging modified package uses warning."""
        lg = MagicMock(spec=logging.Logger)
        info = Mock()
        info.modified = True
        info.name = "mypackage"
        info.commit = "def456"
        info.message = None
        info.build_time = None

        _log_package_info(lg, info)

        lg.warning.assert_called_once()

    def test_log_package_no_commit(self):
        """Test logging package without commit shows n/a."""
        lg = MagicMock(spec=logging.Logger)
        info = Mock()
        info.modified = False
        info.name = "mypackage"
        info.commit = None
        info.message = None
        info.build_time = None

        _log_package_info(lg, info)

        extra = lg.debug.call_args[1]["extra"]
        assert extra["commit"] == "n/a"

    def test_log_package_with_message(self):
        """Test logging includes commit message when present."""
        lg = MagicMock(spec=logging.Logger)
        info = Mock()
        info.modified = False
        info.name = "mypackage"
        info.commit = "def456"
        info.message = "fix: bug fix"
        info.message_short = "fix: bug fix"
        info.build_time = None

        _log_package_info(lg, info)

        extra = lg.debug.call_args[1]["extra"]
        assert extra["commit_msg"] == "fix: bug fix"

    def test_log_package_with_build_time(self):
        """Test logging includes timestamp when present."""
        lg = MagicMock(spec=logging.Logger)
        info = Mock()
        info.modified = False
        info.name = "mypackage"
        info.commit = "def456"
        info.message = None
        info.build_time = datetime(2025, 12, 1, 10, 30, 0)

        _log_package_info(lg, info)

        extra = lg.debug.call_args[1]["extra"]
        assert extra["timestamp"] == "2025-12-01 10:30:00"


class TestVersionConfigurer:
    """Tests for VersionConfigurer class."""

    @pytest.fixture
    def mock_app_builder(self):
        """Create a mock AppBuilder."""
        builder = MagicMock()
        builder._name = "testapp"
        builder._version = None
        builder._version_tracker = None
        builder._build_info = None
        builder._custom_args = []
        builder.advanced = MagicMock()
        builder.advanced.with_hook_builder.return_value = builder.advanced
        builder.advanced.done.return_value = builder
        return builder

    def test_init(self, mock_app_builder):
        """Test VersionConfigurer initialization."""
        configurer = VersionConfigurer(mock_app_builder)
        assert configurer._app_builder is mock_app_builder
        assert configurer._packages == []
        assert configurer._build_info is None
        assert configurer._log_on_startup is True

    def test_with_semver(self, mock_app_builder):
        """Test setting version string."""
        configurer = VersionConfigurer(mock_app_builder)
        result = configurer.with_semver("1.2.3")

        assert result is configurer  # Fluent API
        assert mock_app_builder._version == "1.2.3"

    def test_with_package(self, mock_app_builder):
        """Test tracking a package."""
        configurer = VersionConfigurer(mock_app_builder)
        result = configurer.with_package("mylib")

        assert result is configurer
        assert "mylib" in configurer._packages

    def test_with_multiple_packages(self, mock_app_builder):
        """Test tracking multiple packages."""
        configurer = VersionConfigurer(mock_app_builder)
        configurer.with_package("lib1").with_package("lib2")

        assert "lib1" in configurer._packages
        assert "lib2" in configurer._packages

    def test_with_startup_log(self, mock_app_builder):
        """Test enabling startup logging."""
        configurer = VersionConfigurer(mock_app_builder)
        configurer._log_on_startup = False
        result = configurer.with_startup_log()

        assert result is configurer
        assert configurer._log_on_startup is True

    def test_without_startup_log(self, mock_app_builder):
        """Test disabling startup logging."""
        configurer = VersionConfigurer(mock_app_builder)
        result = configurer.without_startup_log()

        assert result is configurer
        assert configurer._log_on_startup is False

    def test_with_build_info_default_path(
        self, mock_app_builder, tmp_path, monkeypatch
    ):
        """Test with_build_info uses cwd by default."""
        # Create a fake _build_info.py
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text('COMMIT_HASH = "abc123"\nCOMMIT_SHORT = "abc123"\n')

        monkeypatch.chdir(tmp_path)

        configurer = VersionConfigurer(mock_app_builder)
        result = configurer.with_build_info()

        assert result is configurer
        assert configurer._build_info is not None

    def test_with_build_info_string_path(self, mock_app_builder, tmp_path):
        """Test with_build_info with string path."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text('COMMIT_HASH = "def456"\nCOMMIT_SHORT = "def456"\n')

        configurer = VersionConfigurer(mock_app_builder)
        result = configurer.with_build_info(str(build_info_file))

        assert result is configurer
        assert configurer._build_info is not None

    def test_with_build_info_path_object(self, mock_app_builder, tmp_path):
        """Test with_build_info with Path object."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text('COMMIT_HASH = "ghi789"\nCOMMIT_SHORT = "ghi789"\n')

        configurer = VersionConfigurer(mock_app_builder)
        result = configurer.with_build_info(build_info_file)

        assert result is configurer
        assert configurer._build_info is not None

    def test_done_returns_app_builder(self, mock_app_builder):
        """Test done() returns the app builder."""
        configurer = VersionConfigurer(mock_app_builder)
        result = configurer.done()

        assert result is mock_app_builder

    def test_done_with_packages_creates_tracker(self, mock_app_builder):
        """Test done() creates tracker when packages specified."""
        configurer = VersionConfigurer(mock_app_builder)
        configurer.with_package("pytest")
        configurer.done()

        assert mock_app_builder._version_tracker is not None

    def test_done_without_packages_no_tracker(self, mock_app_builder):
        """Test done() doesn't create tracker when no packages."""
        configurer = VersionConfigurer(mock_app_builder)
        configurer.done()

        assert mock_app_builder._version_tracker is None

    def test_done_sets_build_info(self, mock_app_builder, tmp_path):
        """Test done() sets build info on app builder."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text('COMMIT_HASH = "abc123"\nCOMMIT_SHORT = "abc123"\n')

        configurer = VersionConfigurer(mock_app_builder)
        configurer.with_build_info(build_info_file)
        configurer.done()

        assert mock_app_builder._build_info is not None

    def test_done_registers_startup_hook(self, mock_app_builder, tmp_path):
        """Test done() registers startup hook when logging enabled."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text('COMMIT_HASH = "abc123"\nCOMMIT_SHORT = "abc123"\n')

        configurer = VersionConfigurer(mock_app_builder)
        configurer.with_build_info(build_info_file)
        configurer.done()

        # Should have registered a hook via advanced configurer
        mock_app_builder.advanced.with_hook_builder.assert_called_once()

    def test_done_no_hook_when_logging_disabled(self, mock_app_builder, tmp_path):
        """Test done() doesn't register hook when logging disabled."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text('COMMIT_HASH = "abc123"\nCOMMIT_SHORT = "abc123"\n')

        configurer = VersionConfigurer(mock_app_builder)
        configurer.with_build_info(build_info_file)
        configurer.without_startup_log()
        configurer.done()

        # Should not have registered a hook
        mock_app_builder.advanced.with_hook_builder.assert_not_called()

    def test_done_no_hook_when_nothing_to_log(self, mock_app_builder):
        """Test done() doesn't register hook when nothing to log."""
        configurer = VersionConfigurer(mock_app_builder)
        configurer.done()

        # No build_info and no packages = no hook
        mock_app_builder.advanced.with_hook_builder.assert_not_called()

    def test_done_adds_version_argument(self, mock_app_builder):
        """Test done() adds --version argument when version is set."""
        mock_app_builder._version = "1.0.0"
        configurer = VersionConfigurer(mock_app_builder)
        configurer.done()

        # Should have added --version to custom args
        assert len(mock_app_builder._custom_args) == 1
        args, kwargs = mock_app_builder._custom_args[0]
        assert "--version" in args
        assert kwargs["app_name"] == "testapp"
        assert kwargs["app_version"] == "1.0.0"

    def test_done_no_version_argument_without_version(self, mock_app_builder):
        """Test done() doesn't add --version when version not set."""
        configurer = VersionConfigurer(mock_app_builder)
        configurer.done()

        # No version set = no --version argument
        assert len(mock_app_builder._custom_args) == 0

    def test_done_version_argument_includes_build_info(
        self, mock_app_builder, tmp_path
    ):
        """Test done() passes build_info to version argument."""
        mock_app_builder._version = "1.0.0"
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text('COMMIT_HASH = "abc123"\nCOMMIT_SHORT = "abc123"\n')

        configurer = VersionConfigurer(mock_app_builder)
        configurer.with_build_info(build_info_file)
        configurer.done()

        args, kwargs = mock_app_builder._custom_args[0]
        assert kwargs["build_info"] is not None
        assert kwargs["build_info"].commit == "abc123"

    def test_done_version_argument_includes_tracker(self, mock_app_builder):
        """Test done() passes tracker to version argument."""
        mock_app_builder._version = "1.0.0"
        configurer = VersionConfigurer(mock_app_builder)
        configurer.with_package("pytest")
        configurer.done()

        args, kwargs = mock_app_builder._custom_args[0]
        assert kwargs["tracker"] is not None


class TestStartupHookBehavior:
    """Tests for the startup hook callback behavior."""

    def test_startup_hook_logs_build_info(self, tmp_path):
        """Test startup hook actually logs build info when invoked."""

        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text('COMMIT_HASH = "abc123"\nCOMMIT_SHORT = "abc123"\n')

        mock_builder = MagicMock()
        mock_builder._version = None
        mock_builder._version_tracker = None
        mock_builder._build_info = None
        mock_builder.advanced = MagicMock()

        # Capture the hook builder to get the callback
        captured_hook_builder = None

        def capture_hook(hook_builder):
            nonlocal captured_hook_builder
            captured_hook_builder = hook_builder
            return mock_builder.advanced

        mock_builder.advanced.with_hook_builder.side_effect = capture_hook
        mock_builder.advanced.done.return_value = mock_builder

        configurer = VersionConfigurer(mock_builder)
        configurer.with_build_info(build_info_file)
        configurer.done()

        # Verify hook was registered
        assert captured_hook_builder is not None

        # Now invoke the callback directly
        mock_app = MagicMock()
        mock_app.lg = MagicMock(spec=logging.Logger)

        context = MagicMock()
        context.application = mock_app

        # Get the on_startup callback from the hook builder
        for callback, priority, is_async, condition in captured_hook_builder._hooks[
            "startup"
        ]:
            callback(context)

        # Verify build info was logged
        mock_app.lg.debug.assert_called()

    def test_startup_hook_logs_packages(self, tmp_path):
        """Test startup hook logs tracked packages when invoked."""

        mock_builder = MagicMock()
        mock_builder._version = None
        mock_builder._version_tracker = None
        mock_builder._build_info = None
        mock_builder.advanced = MagicMock()

        captured_hook_builder = None

        def capture_hook(hook_builder):
            nonlocal captured_hook_builder
            captured_hook_builder = hook_builder
            return mock_builder.advanced

        mock_builder.advanced.with_hook_builder.side_effect = capture_hook
        mock_builder.advanced.done.return_value = mock_builder

        configurer = VersionConfigurer(mock_builder)
        configurer.with_package("pytest")  # Track a real package
        configurer.done()

        assert captured_hook_builder is not None

        # Invoke the callback
        mock_app = MagicMock()
        mock_app.lg = MagicMock(spec=logging.Logger)

        context = MagicMock()
        context.application = mock_app

        for callback, priority, is_async, condition in captured_hook_builder._hooks[
            "startup"
        ]:
            callback(context)

        # Verify package was logged
        mock_app.lg.debug.assert_called()

    def test_startup_hook_handles_missing_logger(self):
        """Test startup hook handles application without lg attribute."""

        mock_builder = MagicMock()
        mock_builder._version = None
        mock_builder._version_tracker = None
        mock_builder._build_info = None
        mock_builder.advanced = MagicMock()

        captured_hook_builder = None

        def capture_hook(hook_builder):
            nonlocal captured_hook_builder
            captured_hook_builder = hook_builder
            return mock_builder.advanced

        mock_builder.advanced.with_hook_builder.side_effect = capture_hook
        mock_builder.advanced.done.return_value = mock_builder

        configurer = VersionConfigurer(mock_builder)
        configurer.with_package("pytest")
        configurer.done()

        # Create context with application that has no lg
        context = MagicMock()
        context.application = MagicMock(spec=[])  # No lg attribute

        # Should not raise - callback returns early
        for callback, priority, is_async, condition in captured_hook_builder._hooks[
            "startup"
        ]:
            callback(context)  # Should not raise
