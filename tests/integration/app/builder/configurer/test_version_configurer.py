# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.app.builder.configurer.version that read _build_info.py from disk."""

import pytest

from appinfra.app.builder.app import AppBuilder
from appinfra.app.builder.configurer.version import VersionConfigurer

BUILD_INFO_SRC = 'COMMIT_HASH = "abc123"\nCOMMIT_SHORT = "abc123"\n'


def _startup_hooks(builder: AppBuilder) -> list:
    """Startup callbacks registered on the builder's hook manager."""
    return builder._hooks.get_hooks("startup")


class TestVersionConfigurer:
    """Tests for VersionConfigurer class."""

    @pytest.fixture
    def app_builder(self):
        """A real AppBuilder: done() writes to its version fields and hook manager."""
        return AppBuilder("testapp")

    def test_with_build_info_default_path(self, app_builder, tmp_path, monkeypatch):
        """Test with_build_info uses cwd by default."""
        # Create a fake _build_info.py
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text(BUILD_INFO_SRC)

        monkeypatch.chdir(tmp_path)

        configurer = VersionConfigurer(app_builder)
        result = configurer.with_build_info()

        assert result is configurer
        assert app_builder._build_info is not None

    def test_with_build_info_string_path(self, app_builder, tmp_path):
        """Test with_build_info with string path."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text('COMMIT_HASH = "def456"\nCOMMIT_SHORT = "def456"\n')

        configurer = VersionConfigurer(app_builder)
        result = configurer.with_build_info(str(build_info_file))

        assert result is configurer
        assert app_builder._build_info is not None

    def test_with_build_info_path_object(self, app_builder, tmp_path):
        """Test with_build_info with Path object."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text('COMMIT_HASH = "ghi789"\nCOMMIT_SHORT = "ghi789"\n')

        configurer = VersionConfigurer(app_builder)
        result = configurer.with_build_info(build_info_file)

        assert result is configurer
        assert app_builder._build_info is not None

    def test_done_sets_build_info(self, app_builder, tmp_path):
        """Test done() sets build info on app builder."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text(BUILD_INFO_SRC)

        configurer = VersionConfigurer(app_builder)
        configurer.with_build_info(build_info_file)
        configurer.done()

        assert app_builder._build_info is not None

    def test_build_registers_startup_hook(self, app_builder, tmp_path):
        """build() registers one startup hook at priority 90 when logging enabled."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text(BUILD_INFO_SRC)
        app_builder.version.with_build_info(build_info_file).done()

        app_builder.build()

        assert len(_startup_hooks(app_builder)) == 1
        assert app_builder._hooks._hook_metadata["startup"][0]["priority"] == 90

    def test_build_no_hook_when_logging_disabled(self, app_builder, tmp_path):
        """without_startup_log suppresses the hook."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text(BUILD_INFO_SRC)
        app_builder.version.with_build_info(
            build_info_file
        ).without_startup_log().done()

        app_builder.build()

        assert not app_builder._hooks.has_hooks("startup")

    def test_call_keyword_form(self, app_builder, tmp_path):
        """__call__ maps keywords onto the chained methods and returns the builder."""
        build_info_file = tmp_path / "_build_info.py"
        build_info_file.write_text(BUILD_INFO_SRC)

        result = app_builder.version(
            semver="2.0.0",
            build_info=build_info_file,
            package=["pytest", "packaging"],
            startup_log=False,
        )

        assert result is app_builder
        assert app_builder._version == "2.0.0"
        assert app_builder._build_info is not None
        assert app_builder._version_packages == ["pytest", "packaging"]
        assert app_builder._version_startup_log is False

        app_builder.build()

        assert app_builder._version_tracker is not None
        assert not app_builder._hooks.has_hooks("startup")
