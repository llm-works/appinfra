# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for version_tool module."""

import json
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

from appinfra.cli.tools.version_tool import VersionTool, _get_build_info


class TestGetBuildInfo:
    """Tests for _get_build_info function."""

    def test_returns_dict_with_expected_keys(self):
        """Test returns dict with all expected keys."""
        result = _get_build_info()

        assert "commit" in result
        assert "full" in result
        assert "message" in result
        assert "time" in result
        assert "modified" in result

    def test_returns_values_from_installed_build_info(self):
        """Test returns actual values from _build_info module."""
        result = _get_build_info()

        # Either we have real build info or None values
        # Just verify the structure is correct
        assert isinstance(result, dict)
        assert len(result) == 5


class TestVersionTool:
    """Tests for VersionTool class."""

    @pytest.fixture
    def tool(self):
        """Create a VersionTool instance."""
        return VersionTool()

    def test_init(self, tool):
        """Test tool initialization."""
        assert tool.config.name == "version"
        assert "version" in tool.config.help_text.lower()

    def test_add_args(self, tool):
        """Test argument parser setup."""
        import argparse

        parser = argparse.ArgumentParser()
        tool.add_args(parser)

        # Verify key arguments exist by parsing empty args
        args = parser.parse_args([])
        assert hasattr(args, "field")
        assert hasattr(args, "package")
        assert hasattr(args, "as_json")
        assert hasattr(args, "output_file")
        assert hasattr(args, "with_stub")

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_default_with_commit(
        self, mock_appinfra, mock_get_info, tool, capsys
    ):
        """Test default output with commit info."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {
            "commit": "abc1234",
            "modified": False,
        }

        result = tool.run(field=None, as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert "appinfra 1.2.3 (abc1234)" in captured.out

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_default_with_modified(
        self, mock_appinfra, mock_get_info, tool, capsys
    ):
        """Test default output shows * for modified."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {
            "commit": "abc1234",
            "modified": True,
        }

        result = tool.run(field=None, as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert "appinfra 1.2.3 (abc1234*)" in captured.out

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_default_no_commit(self, mock_appinfra, mock_get_info, tool, capsys):
        """Test default output without commit info."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {
            "commit": None,
            "modified": None,
        }

        result = tool.run(field=None, as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert "appinfra 1.2.3" in captured.out
        assert "(" not in captured.out

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_field_semver(self, mock_appinfra, mock_get_info, tool, capsys):
        """Test semver field output."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {"commit": "abc1234"}

        result = tool.run(field="semver", as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "1.2.3"

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_field_commit(self, mock_appinfra, mock_get_info, tool, capsys):
        """Test commit field output."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {"commit": "abc1234"}

        result = tool.run(field="commit", as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "abc1234"

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_field_modified_true(
        self, mock_appinfra, mock_get_info, tool, capsys
    ):
        """Test modified field output when True."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {"modified": True}

        result = tool.run(field="modified", as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "true"

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_field_modified_false(
        self, mock_appinfra, mock_get_info, tool, capsys
    ):
        """Test modified field output when False."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {"modified": False}

        result = tool.run(field="modified", as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "false"

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_field_modified_unknown(
        self, mock_appinfra, mock_get_info, tool, capsys
    ):
        """Test modified field output when None."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {"modified": None}

        result = tool.run(field="modified", as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "unknown"

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_field_empty_value(self, mock_appinfra, mock_get_info, tool, capsys):
        """Test field output when value is empty."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {"time": None}

        result = tool.run(field="time", as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == ""

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_json(self, mock_appinfra, mock_get_info, tool, capsys):
        """Test JSON output."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {
            "commit": "abc1234",
            "full": "abc1234567890",
            "message": "test",
            "time": "2025-12-01T00:00:00Z",
            "modified": True,
        }

        result = tool.run(field=None, as_json=True)

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["semver"] == "1.2.3"
        assert data["commit"] == "abc1234"
        assert data["modified"] is True

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_field_full(self, mock_appinfra, mock_get_info, tool, capsys):
        """Test full commit hash field output."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {"full": "abc1234567890abcdef"}

        result = tool.run(field="full", as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "abc1234567890abcdef"

    @patch("appinfra.cli.tools.version_tool._get_build_info")
    @patch("appinfra.cli.tools.version_tool.appinfra")
    def test_output_field_message(self, mock_appinfra, mock_get_info, tool, capsys):
        """Test message field output."""
        mock_appinfra.__version__ = "1.2.3"
        mock_get_info.return_value = {"message": "feat: add feature"}

        result = tool.run(field="message", as_json=False)

        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "feat: add feature"


class TestVersionToolInitHook:
    """Tests for init-hook subcommand."""

    @pytest.fixture
    def tool(self):
        """Create a VersionTool instance."""
        return VersionTool()

    def test_init_hook_without_package_returns_error(self, tool, capsys):
        """Test init-hook requires package name."""
        result = tool.run(field="init-hook", package=None)

        assert result == 1
        captured = capsys.readouterr()
        assert "package name is required" in captured.err

    def test_init_hook_invalid_package_name_returns_error(self, tool, capsys):
        """Test init-hook rejects invalid package names."""
        result = tool.run(field="init-hook", package="invalid-name")

        assert result == 1
        captured = capsys.readouterr()
        assert "invalid package name" in captured.err

    def test_init_hook_generates_setup_py_to_stdout(self, tool, capsys):
        """Test init-hook outputs setup.py to stdout."""
        result = tool.run(field="init-hook", package="mypackage")

        assert result == 0
        captured = capsys.readouterr()
        assert 'PACKAGE_NAME = "mypackage"' in captured.out
        assert "from setuptools import setup" in captured.out
        assert "class BuildPyWithBuildInfo" in captured.out

    def test_init_hook_generates_setup_py_to_file(self, tool, capsys, tmp_path):
        """Test init-hook writes setup.py to file."""
        output_file = tmp_path / "setup.py"

        result = tool.run(
            field="init-hook", package="mypackage", output_file=str(output_file)
        )

        assert result == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert 'PACKAGE_NAME = "mypackage"' in content
        captured = capsys.readouterr()
        assert "Generated" in captured.err

    def test_init_hook_with_stub_creates_build_info(self, tool, capsys, tmp_path):
        """Test init-hook with --with-stub creates _build_info.py."""
        # Create the package directory
        pkg_dir = tmp_path / "mypackage"
        pkg_dir.mkdir()

        # Change to tmp_path so relative path works
        import os

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = tool.run(field="init-hook", package="mypackage", with_stub=True)

            assert result == 0
            stub_file = pkg_dir / "_build_info.py"
            assert stub_file.exists()
            content = stub_file.read_text()
            assert 'COMMIT_HASH = ""' in content
        finally:
            os.chdir(original_cwd)

    def test_init_hook_with_stub_warns_if_dir_missing(self, tool, capsys, tmp_path):
        """Test init-hook with --with-stub warns if package dir doesn't exist."""
        import os

        original_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = tool.run(field="init-hook", package="nonexistent", with_stub=True)

            assert result == 0  # Still succeeds for setup.py
            captured = capsys.readouterr()
            assert "warning" in captured.err.lower()
            assert "does not exist" in captured.err
        finally:
            os.chdir(original_cwd)

    def test_init_hook_valid_package_names(self, tool):
        """Test init-hook accepts valid package names."""
        valid_names = ["mypackage", "my_package", "Package1", "_private"]

        for name in valid_names:
            result = tool.run(field="init-hook", package=name)
            assert result == 0, f"Expected {name} to be valid"

    def test_init_hook_invalid_package_names(self, tool, capsys):
        """Test init-hook rejects invalid package names."""
        invalid_names = ["my-package", "123package", "my.package", "my package"]

        for name in invalid_names:
            result = tool.run(field="init-hook", package=name)
            assert result == 1, f"Expected {name} to be invalid"
            # Clear captured output for next iteration
            capsys.readouterr()
