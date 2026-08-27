# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for setup_hook module.

Tests the reusable setup.py hook for downstream projects to adopt version tracking.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from appinfra.version.setup_hook import (
    _generate_build_info,
    _get_git_info,
    _run_git,
    get_stub_content,
    make_build_py_class,
)

# =============================================================================
# Test _run_git
# =============================================================================


@pytest.mark.unit
class TestRunGit:
    """Test _run_git helper function."""

    @patch("subprocess.run")
    def test_returns_stdout_on_success(self, mock_run):
        """Test returns stdout when git succeeds."""
        mock_run.return_value = MagicMock(returncode=0, stdout="output\n")

        result = _run_git("status")
        assert result == "output"

    @patch("subprocess.run")
    def test_returns_none_on_failure(self, mock_run):
        """Test returns None when git fails."""
        mock_run.return_value = MagicMock(returncode=1)

        result = _run_git("status")
        assert result is None

    @patch("subprocess.run")
    def test_handles_subprocess_error(self, mock_run):
        """Test handles subprocess errors."""
        mock_run.side_effect = subprocess.SubprocessError("error")

        result = _run_git("status")
        assert result is None

    @patch("subprocess.run")
    def test_handles_file_not_found(self, mock_run):
        """Test handles git not installed."""
        mock_run.side_effect = FileNotFoundError("git not found")

        result = _run_git("status")
        assert result is None

    @patch("subprocess.run")
    def test_passes_cwd_to_subprocess(self, mock_run, tmp_path):
        """Test passes cwd parameter to subprocess."""
        mock_run.return_value = MagicMock(returncode=0, stdout="output")

        _run_git("status", cwd=tmp_path)

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["cwd"] == tmp_path


# =============================================================================
# Test _get_git_info
# =============================================================================


@pytest.mark.unit
class TestGetGitInfo:
    """Test _get_git_info function."""

    @patch("appinfra.version.setup_hook._run_git")
    def test_returns_commit_info(self, mock_run_git):
        """Test returns commit hash, message, and dirty status."""

        def run_side_effect(*args, **kwargs):
            if "rev-parse" in args:
                return "abc123def456789012345678901234567890abcd"
            elif "--format=%s" in args:
                return "Test commit"
            elif "--porcelain" in args:
                return ""  # Clean repo
            return None

        mock_run_git.side_effect = run_side_effect

        result = _get_git_info()

        assert result is not None
        full, short, message, modified = result
        assert full == "abc123def456789012345678901234567890abcd"
        assert short == "abc123d"
        assert message == "Test commit"
        assert modified is False

    @patch("appinfra.version.setup_hook._run_git")
    def test_returns_none_on_git_failure(self, mock_run_git):
        """Test returns None when git fails."""
        mock_run_git.return_value = None

        result = _get_git_info()
        assert result is None

    @patch("appinfra.version.setup_hook._run_git")
    def test_detects_dirty_repo(self, mock_run_git):
        """Test detects modified working directory."""

        def run_side_effect(*args, **kwargs):
            if "rev-parse" in args:
                return "abc123def456789012345678901234567890abcd"
            elif "--format=%s" in args:
                return "Test commit"
            elif "--porcelain" in args:
                return " M file.py"  # Modified file
            return None

        mock_run_git.side_effect = run_side_effect

        result = _get_git_info()

        assert result is not None
        _, _, _, modified = result
        assert modified is True

    @patch("appinfra.version.setup_hook._run_git")
    def test_passes_cwd_to_run_git(self, mock_run_git, tmp_path):
        """Test passes cwd parameter through to _run_git."""
        mock_run_git.return_value = None

        _get_git_info(cwd=tmp_path)

        # Check that cwd was passed to all calls
        for call in mock_run_git.call_args_list:
            assert call.kwargs.get("cwd") == tmp_path


# =============================================================================
# Test _generate_build_info
# =============================================================================


@pytest.mark.unit
class TestGenerateBuildInfo:
    """Test _generate_build_info function."""

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_generates_file(self, mock_get_info, tmp_path):
        """Test generates _build_info.py file."""
        mock_get_info.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            "Test commit",
            False,  # modified
        )

        result = _generate_build_info(tmp_path)

        assert result is True
        build_info = tmp_path / "_build_info.py"
        assert build_info.exists()
        content = build_info.read_text()
        assert 'COMMIT_HASH = "abc123def456789012345678901234567890abcd"' in content
        assert 'COMMIT_SHORT = "abc123d"' in content
        assert 'COMMIT_MESSAGE = "Test commit"' in content
        assert "MODIFIED = False" in content
        assert "BUILD_TIME" in content

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_returns_false_without_git(self, mock_get_info, tmp_path, capsys):
        """Test returns False when git info unavailable."""
        mock_get_info.return_value = None

        result = _generate_build_info(tmp_path)

        assert result is False
        captured = capsys.readouterr()
        assert "git info not available" in captured.err

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_escapes_quotes_in_message(self, mock_get_info, tmp_path):
        """Test escapes quotes in commit message."""
        mock_get_info.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            'Fix "bug"',
            True,  # modified
        )

        _generate_build_info(tmp_path)

        content = (tmp_path / "_build_info.py").read_text()
        assert 'COMMIT_MESSAGE = "Fix \\"bug\\""' in content
        assert "MODIFIED = True" in content

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_escapes_backslashes_in_message(self, mock_get_info, tmp_path):
        """Test escapes backslashes in commit message."""
        mock_get_info.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            "Fix path\\to\\file",
            False,
        )

        _generate_build_info(tmp_path)

        content = (tmp_path / "_build_info.py").read_text()
        assert 'COMMIT_MESSAGE = "Fix path\\\\to\\\\file"' in content

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_prints_success_message(self, mock_get_info, tmp_path, capsys):
        """Test prints success message with short commit."""
        mock_get_info.return_value = (
            "abc123def456789012345678901234567890abcd",
            "abc123d",
            "Test commit",
            False,
        )

        _generate_build_info(tmp_path)

        captured = capsys.readouterr()
        assert "generated _build_info.py" in captured.err
        assert "abc123d" in captured.err

    @patch("appinfra.version.setup_hook._get_git_info")
    def test_passes_cwd_to_get_git_info(self, mock_get_info, tmp_path):
        """Test passes cwd parameter to _get_git_info."""
        mock_get_info.return_value = None
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        _generate_build_info(tmp_path, cwd=src_dir)

        mock_get_info.assert_called_once_with(src_dir)


# =============================================================================
# Test make_build_py_class
# =============================================================================


@pytest.mark.unit
class TestMakeBuildPyClass:
    """Test make_build_py_class factory function."""

    def test_returns_build_py_subclass(self):
        """Test returns a subclass of build_py."""
        from setuptools.command.build_py import build_py

        cls = make_build_py_class("mypackage")

        assert issubclass(cls, build_py)

    def test_class_has_correct_docstring(self):
        """Test returned class has descriptive docstring."""
        cls = make_build_py_class("mypackage")

        assert "build_py" in cls.__doc__
        assert "_build_info.py" in cls.__doc__

    @patch("appinfra.version.setup_hook._generate_build_info")
    def test_run_generates_build_info(self, mock_generate, tmp_path):
        """Test run() generates build info in build directory."""
        # Create package directory in build_lib
        build_lib = tmp_path / "build" / "lib"
        pkg_dir = build_lib / "mypackage"
        pkg_dir.mkdir(parents=True)

        cls = make_build_py_class("mypackage")
        instance = cls.__new__(cls)

        # Mock the parent run() and set build_lib
        instance.build_lib = str(build_lib)
        with patch.object(cls.__bases__[0], "run"):
            instance.run()

        mock_generate.assert_called_once_with(pkg_dir)

    @patch("appinfra.version.setup_hook._generate_build_info")
    def test_run_skips_when_package_not_in_build(self, mock_generate, tmp_path):
        """Test run() skips when package directory doesn't exist in build."""
        build_lib = tmp_path / "build" / "lib"
        build_lib.mkdir(parents=True)
        # Don't create the package directory

        cls = make_build_py_class("mypackage")
        instance = cls.__new__(cls)

        instance.build_lib = str(build_lib)
        with patch.object(cls.__bases__[0], "run"):
            instance.run()

        mock_generate.assert_not_called()

    @patch("appinfra.version.setup_hook._generate_build_info")
    def test_run_skips_when_no_build_lib(self, mock_generate):
        """Test run() skips when build_lib is not set."""
        cls = make_build_py_class("mypackage")
        instance = cls.__new__(cls)

        instance.build_lib = None
        with patch.object(cls.__bases__[0], "run"):
            instance.run()

        mock_generate.assert_not_called()

    def test_different_package_names(self):
        """Test works with different package names."""
        cls1 = make_build_py_class("package_a")
        cls2 = make_build_py_class("package_b")

        # Both should be valid classes but independent
        assert cls1 is not cls2
        assert issubclass(cls1, object)
        assert issubclass(cls2, object)


# =============================================================================
# Test get_stub_content
# =============================================================================


@pytest.mark.unit
class TestGetStubContent:
    """Test get_stub_content function."""

    def test_returns_stub_template(self):
        """Test returns valid stub template."""
        content = get_stub_content()

        assert 'COMMIT_HASH = ""' in content
        assert 'COMMIT_SHORT = ""' in content
        assert 'COMMIT_MESSAGE = ""' in content
        assert 'BUILD_TIME = ""' in content
        assert "MODIFIED = None" in content

    def test_stub_is_valid_python(self, tmp_path):
        """Test stub content is valid Python that can be imported."""
        content = get_stub_content()

        stub_file = tmp_path / "_build_info.py"
        stub_file.write_text(content)

        # Should be importable
        import importlib.util

        spec = importlib.util.spec_from_file_location("_build_info", stub_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert module.COMMIT_HASH == ""
        assert module.COMMIT_SHORT == ""
        assert module.COMMIT_MESSAGE == ""
        assert module.BUILD_TIME == ""
        assert module.MODIFIED is None

    def test_stub_has_docstring(self):
        """Test stub has explanatory docstring."""
        content = get_stub_content()

        assert '"""Build information' in content
        assert "auto-generated" in content

    def test_stub_has_comment_about_population(self):
        """Test stub has comment explaining it gets populated during install."""
        content = get_stub_content()

        assert "Stub values" in content or "populated during pip install" in content


# =============================================================================
# Test generate_standalone_setup
# =============================================================================


@pytest.mark.unit
class TestGenerateStandaloneSetup:
    """Test generate_standalone_setup function."""

    def test_returns_setup_py_content(self):
        """Test returns valid setup.py content."""
        from appinfra.version.setup_hook import generate_standalone_setup

        content = generate_standalone_setup("mypackage")

        assert "from setuptools import setup" in content
        assert "from setuptools.command.build_py import build_py" in content
        assert 'PACKAGE_NAME = "mypackage"' in content
        assert "class BuildPyWithBuildInfo" in content

    def test_substitutes_package_name(self):
        """Test package name is substituted correctly."""
        from appinfra.version.setup_hook import generate_standalone_setup

        content = generate_standalone_setup("my_custom_pkg")

        assert 'PACKAGE_NAME = "my_custom_pkg"' in content
        # Ensure the template placeholder is gone
        assert "{package_name}" not in content

    def test_generated_code_is_valid_python(self, tmp_path):
        """Test generated setup.py is valid Python syntax."""
        from appinfra.version.setup_hook import generate_standalone_setup

        content = generate_standalone_setup("testpkg")

        # Should compile without errors
        compile(content, "setup.py", "exec")

        # Write and verify it's importable (without executing setup())
        setup_file = tmp_path / "setup_test.py"
        # Replace setup() call with pass to allow import without side effects
        modified_content = content.replace(
            'setup(cmdclass={"build_py": BuildPyWithBuildInfo})',
            "pass  # setup() replaced for testing",
        )
        setup_file.write_text(modified_content)

        import importlib.util

        spec = importlib.util.spec_from_file_location("setup_test", setup_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Verify key components exist
        assert hasattr(module, "PACKAGE_NAME")
        assert module.PACKAGE_NAME == "testpkg"
        assert hasattr(module, "BuildPyWithBuildInfo")

    def test_has_no_appinfra_imports(self):
        """Test generated code has no appinfra imports (self-contained)."""
        from appinfra.version.setup_hook import generate_standalone_setup

        content = generate_standalone_setup("mypackage")

        assert "from appinfra" not in content
        assert "import appinfra" not in content

    def test_has_docstring(self):
        """Test generated setup.py has explanatory docstring."""
        from appinfra.version.setup_hook import generate_standalone_setup

        content = generate_standalone_setup("mypackage")

        assert '"""' in content
        assert "version tracking" in content.lower()
        assert "Generated by" in content

    def test_contains_git_functions(self):
        """Test generated code contains git helper functions."""
        from appinfra.version.setup_hook import generate_standalone_setup

        content = generate_standalone_setup("mypackage")

        assert "def _run_git" in content
        assert "def _get_git_info" in content
        assert "def _generate_build_info" in content
        assert "subprocess.run" in content
        assert '["git"' in content

    def test_contains_build_py_class(self):
        """Test generated code contains BuildPyWithBuildInfo class."""
        from appinfra.version.setup_hook import generate_standalone_setup

        content = generate_standalone_setup("mypackage")

        assert "class BuildPyWithBuildInfo(build_py):" in content
        assert "def run(self):" in content
        assert "super().run()" in content
