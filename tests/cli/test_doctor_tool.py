# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the DoctorTool CLI module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from appinfra.cli.tools.doctor_tool import CheckResult, DoctorTool


@pytest.mark.unit
class TestCheckResult:
    """Tests for CheckResult dataclass."""

    def test_check_result_passed(self):
        """Test CheckResult with passed status."""
        result = CheckResult(name="Test", passed=True, message="OK")
        assert result.name == "Test"
        assert result.passed is True
        assert result.message == "OK"
        assert result.suggestion is None

    def test_check_result_failed_with_suggestion(self):
        """Test CheckResult with failed status and suggestion."""
        result = CheckResult(
            name="Test",
            passed=False,
            message="Failed",
            suggestion="Fix this",
        )
        assert result.passed is False
        assert result.suggestion == "Fix this"


@pytest.mark.unit
class TestDoctorTool:
    """Tests for DoctorTool."""

    def test_init(self):
        """Test DoctorTool initialization."""
        tool = DoctorTool()
        assert tool.config.name == "doctor"
        assert "dr" in tool.config.aliases

    def test_check_python_version_passes(self):
        """Test Python version check passes for 3.11+."""
        tool = DoctorTool()
        result = tool._check_python_version()
        assert result.name == "Python version"
        # Should pass on Python 3.11+
        assert result.passed is True
        assert ">= 3.11" in result.message

    def test_check_python_version_fails_old_python(self):
        """Test Python version check fails for old Python."""
        tool = DoctorTool()
        # Create a mock version_info with the required attributes
        mock_version = MagicMock()
        mock_version.major = 3
        mock_version.minor = 10
        mock_version.micro = 0
        mock_version.__ge__ = lambda self, other: (3, 10, 0) >= other

        with patch(
            "appinfra.cli.tools.doctor_tool.sys.version_info",
            mock_version,
        ):
            result = tool._check_python_version()
            # With mocked old version, should fail
            assert result.passed is False
            assert result.suggestion is not None

    def test_extract_version_standard(self):
        """Test version extraction from standard output."""
        tool = DoctorTool()
        assert tool._extract_version("ruff 0.8.0") == "0.8.0"
        assert tool._extract_version("mypy 1.19.0") == "1.19.0"
        assert tool._extract_version("pytest 9.0.1") == "9.0.1"

    def test_extract_version_empty(self):
        """Test version extraction with empty output."""
        tool = DoctorTool()
        assert tool._extract_version("") == "installed"

    def test_extract_version_no_version(self):
        """Test version extraction when no version pattern found."""
        tool = DoctorTool()
        assert tool._extract_version("tool") == "installed"

    def test_check_single_tool_installed(self):
        """Test check for installed tool."""
        tool = DoctorTool()
        # pytest should be installed in test env
        result = tool._check_single_tool("pytest", "pytest", "pip install pytest")
        assert result.passed is True
        assert result.name == "pytest"

    def test_check_single_tool_not_installed(self):
        """Test check for non-installed tool."""
        tool = DoctorTool()
        result = tool._check_single_tool(
            "nonexistent", "nonexistent_module_xyz", "pip install nonexistent"
        )
        assert result.passed is False
        assert "not installed" in result.message or "check failed" in result.message

    def test_check_required_tools(self):
        """Test checking all required tools."""
        tool = DoctorTool()
        results = tool._check_required_tools()
        assert len(results) == 3  # ruff, pytest, mypy
        assert all(isinstance(r, CheckResult) for r in results)

    def test_validate_package_structure_valid(self, tmp_path):
        """Test package validation with valid structure."""
        # Create a valid package
        pkg_dir = tmp_path / "mypackage"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")

        tool = DoctorTool()
        result = tool._validate_package_structure("mypackage", tmp_path)
        assert result.passed is True
        assert "valid Python package" in result.message

    def test_validate_package_structure_missing_dir(self, tmp_path):
        """Test package validation with missing directory."""
        tool = DoctorTool()
        result = tool._validate_package_structure("nonexistent", tmp_path)
        assert result.passed is False
        assert "does not exist" in result.message

    def test_validate_package_structure_missing_init(self, tmp_path):
        """Test package validation with missing __init__.py."""
        pkg_dir = tmp_path / "mypackage"
        pkg_dir.mkdir()

        tool = DoctorTool()
        result = tool._validate_package_structure("mypackage", tmp_path)
        assert result.passed is False
        assert "__init__.py" in result.message

    def test_check_package_name_not_set(self):
        """Test package name check when not set."""
        tool = DoctorTool()
        mock_args = MagicMock()
        mock_args.pkg_name = None
        mock_args.project_root = "."
        tool._parsed_args = mock_args

        with patch.dict(os.environ, {}, clear=True):
            # Remove INFRA_DEV_PKG_NAME if present
            os.environ.pop("INFRA_DEV_PKG_NAME", None)
            result = tool._check_package_name()
            assert result.passed is False
            assert "not set" in result.message

    def test_check_tests_directory_exists(self, tmp_path):
        """Test tests directory check when exists with tests."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_example.py").write_text("")

        tool = DoctorTool()
        mock_args = MagicMock()
        mock_args.project_root = str(tmp_path)
        tool._parsed_args = mock_args

        result = tool._check_tests_directory()
        assert result.passed is True
        assert "1 test files found" in result.message

    def test_check_tests_directory_missing(self, tmp_path):
        """Test tests directory check when missing."""
        tool = DoctorTool()
        mock_args = MagicMock()
        mock_args.project_root = str(tmp_path)
        tool._parsed_args = mock_args

        result = tool._check_tests_directory()
        assert result.passed is False
        assert "not found" in result.message

    def test_check_tests_directory_empty(self, tmp_path):
        """Test tests directory check when empty."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        tool = DoctorTool()
        mock_args = MagicMock()
        mock_args.project_root = str(tmp_path)
        tool._parsed_args = mock_args

        result = tool._check_tests_directory()
        assert result.passed is False
        assert "no test files" in result.message

    def test_find_config_file_found(self, tmp_path):
        """Test config file search when found."""
        (tmp_path / "Makefile.local").write_text("# config")

        tool = DoctorTool()
        result = tool._find_config_file(tmp_path)
        assert result is not None
        assert result.name == "Makefile.local"

    def test_find_config_file_not_found(self, tmp_path):
        """Test config file search when not found."""
        tool = DoctorTool()
        result = tool._find_config_file(tmp_path)
        assert result is None

    def test_check_config_syntax_no_file(self, tmp_path):
        """Test config syntax check when no config file."""
        tool = DoctorTool()
        mock_args = MagicMock()
        mock_args.project_root = str(tmp_path)
        tool._parsed_args = mock_args

        result = tool._check_config_syntax()
        assert result.passed is True
        assert "no Makefile.local found" in result.message

    def test_output_pretty(self, capsys):
        """Test pretty output format."""
        tool = DoctorTool()
        results = [
            CheckResult("Test1", True, "OK"),
            CheckResult("Test2", False, "Failed", "Fix it"),
        ]

        exit_code = tool._output_pretty(results)
        assert exit_code == 1  # Has failures

        captured = capsys.readouterr()
        assert "[ok]" in captured.out
        assert "[X]" in captured.out
        assert "Fix it" in captured.out

    def test_output_pretty_all_passed(self, capsys):
        """Test pretty output when all checks pass."""
        tool = DoctorTool()
        results = [
            CheckResult("Test1", True, "OK"),
            CheckResult("Test2", True, "Also OK"),
        ]

        exit_code = tool._output_pretty(results)
        assert exit_code == 0

        captured = capsys.readouterr()
        assert "All checks passed" in captured.out

    def test_output_json(self, capsys):
        """Test JSON output format."""
        import json

        tool = DoctorTool()
        results = [
            CheckResult("Test1", True, "OK"),
            CheckResult("Test2", False, "Failed", "Fix it"),
        ]

        exit_code = tool._output_json(results)
        assert exit_code == 1

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["passed"] is False
        assert len(output["checks"]) == 2

    def test_run_pretty_output(self, tmp_path, capsys):
        """Test run method with pretty output."""
        # Create minimal valid project structure
        pkg_dir = tmp_path / "mypackage"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_example.py").write_text("")

        tool = DoctorTool()
        mock_args = MagicMock()
        mock_args.pkg_name = "mypackage"
        mock_args.project_root = str(tmp_path)
        mock_args.json = False
        tool._parsed_args = mock_args

        result = tool.run()
        # Should return 0 or 1 depending on checks
        assert result in (0, 1)

        captured = capsys.readouterr()
        assert "Project Health Check" in captured.out

    def test_run_json_output(self, tmp_path, capsys):
        """Test run method with JSON output."""
        import json

        pkg_dir = tmp_path / "mypackage"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_example.py").write_text("")

        tool = DoctorTool()
        mock_args = MagicMock()
        mock_args.pkg_name = "mypackage"
        mock_args.project_root = str(tmp_path)
        mock_args.json = True
        tool._parsed_args = mock_args

        result = tool.run()
        assert result in (0, 1)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "passed" in output
        assert "checks" in output

    def test_check_single_tool_timeout(self):
        """Test check for tool that times out."""
        tool = DoctorTool()
        with patch("subprocess.run", side_effect=TimeoutError()):
            result = tool._check_single_tool("slow", "slow_module", "pip install slow")
            assert result.passed is False

    def test_validate_config_with_make_syntax_error(self, tmp_path):
        """Test config validation with syntax error."""
        config_file = tmp_path / "Makefile.local"
        config_file.write_text("INVALID\n:= SYNTAX")

        tool = DoctorTool()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stderr=b"error: missing separator",
                returncode=2,
            )
            result = tool._validate_config_with_make(config_file, tmp_path)
            assert result.passed is False
            assert "syntax error" in result.message

    def test_validate_config_with_make_valid(self, tmp_path):
        """Test config validation with valid syntax."""
        config_file = tmp_path / "Makefile.local"
        config_file.write_text("VALID := true")

        tool = DoctorTool()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stderr=b"",
                returncode=0,
            )
            result = tool._validate_config_with_make(config_file, tmp_path)
            assert result.passed is True
            assert "syntax valid" in result.message

    def test_validate_config_with_make_exception(self, tmp_path):
        """Test config validation with exception."""
        config_file = tmp_path / "Makefile.local"
        config_file.write_text("VALID := true")

        tool = DoctorTool()

        with patch("subprocess.run", side_effect=Exception("Unknown error")):
            result = tool._validate_config_with_make(config_file, tmp_path)
            assert result.passed is False
            assert "could not validate" in result.message

    def test_validate_config_with_make_timeout(self, tmp_path):
        """Test config validation with timeout."""
        import subprocess

        config_file = tmp_path / "Makefile.local"
        config_file.write_text("VALID := true")

        tool = DoctorTool()

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("make", 5)):
            result = tool._validate_config_with_make(config_file, tmp_path)
            assert result.passed is True
            assert "timed out" in result.message
