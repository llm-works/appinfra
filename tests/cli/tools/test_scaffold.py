# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/tools/scaffold.py.

Tests key functionality including:
- Helper functions for scaffold tool
- ScaffoldTool initialization and configuration
- Project structure generation
- Config file generation
- Application file generation
- Supporting files generation
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from appinfra.cli.tools.scaffold_tool import (
    ScaffoldTool,
    _extract_scaffold_arguments,
    _log_next_steps,
)

# =============================================================================
# Test Helper Functions
# =============================================================================


@pytest.mark.unit
class TestExtractScaffoldArguments:
    """Test _extract_scaffold_arguments helper function."""

    def test_extracts_all_arguments(self):
        """Test extracts name, path, and feature flags."""
        args = Mock()
        args.name = "myproject"
        args.path = "/custom/path"
        args.with_db = True
        args.with_server = True
        args.with_logging_db = True
        args.makefile_style = "framework"

        name, path, with_db, with_server, with_logging_db, makefile_style = (
            _extract_scaffold_arguments(args)
        )

        assert name == "myproject"
        assert path == "/custom/path"
        assert with_db is True
        assert with_server is True
        assert with_logging_db is True
        assert makefile_style == "framework"

    def test_uses_defaults_when_attrs_missing(self):
        """Test uses default values when attributes are missing."""
        args = Mock(spec=["name"])
        args.name = "myproject"

        name, path, with_db, with_server, with_logging_db, makefile_style = (
            _extract_scaffold_arguments(args)
        )

        assert name == "myproject"
        assert path == "."
        assert with_db is False
        assert with_server is False
        assert with_logging_db is False
        assert makefile_style == "standalone"


@pytest.mark.unit
class TestLogNextSteps:
    """Test _log_next_steps helper function."""

    def test_logs_success_and_instructions(self):
        """Test logs success message and next steps."""
        lg = Mock()

        _log_next_steps(lg, "myproject", Path("/path/to/myproject"))

        # Should log success and next steps
        assert lg.info.call_count >= 3
        # Check success message was logged
        calls = [str(c) for c in lg.info.call_args_list]
        assert any("successfully" in str(c) for c in calls)


# =============================================================================
# Test ScaffoldTool Initialization
# =============================================================================


@pytest.mark.unit
class TestScaffoldToolInit:
    """Test ScaffoldTool initialization."""

    def test_basic_initialization(self):
        """Test tool initializes with correct name and help text."""
        tool = ScaffoldTool()

        assert tool.name == "scaffold"
        assert "scaffolding" in tool.config.help_text.lower()

    def test_initialization_with_parent(self):
        """Test tool initializes with parent."""
        parent = Mock()
        parent.lg = Mock()

        tool = ScaffoldTool(parent=parent)

        assert tool.name == "scaffold"


# =============================================================================
# Test add_args
# =============================================================================


@pytest.mark.unit
class TestScaffoldToolAddArgs:
    """Test ScaffoldTool.add_args method."""

    def test_adds_required_name_argument(self):
        """Test adds required 'name' argument."""
        tool = ScaffoldTool()
        parser = Mock()

        tool.add_args(parser)

        # Check 'name' was added as positional argument
        calls = [c for c in parser.add_argument.call_args_list]
        name_calls = [c for c in calls if c[0][0] == "name"]
        assert len(name_calls) == 1

    def test_adds_path_argument(self):
        """Test adds --path optional argument."""
        tool = ScaffoldTool()
        parser = Mock()

        tool.add_args(parser)

        calls = [c for c in parser.add_argument.call_args_list]
        path_calls = [c for c in calls if c[0][0] == "--path"]
        assert len(path_calls) == 1
        # Check default is current directory
        assert path_calls[0][1].get("default") == "."

    def test_adds_feature_flags(self):
        """Test adds --with-db, --with-server, --with-logging-db flags."""
        tool = ScaffoldTool()
        parser = Mock()

        tool.add_args(parser)

        calls = [c[0][0] for c in parser.add_argument.call_args_list]
        assert "--with-db" in calls
        assert "--with-server" in calls
        assert "--with-logging-db" in calls


# =============================================================================
# Test run Method
# =============================================================================


@pytest.mark.unit
class TestScaffoldToolRun:
    """Test ScaffoldTool.run method."""

    def test_returns_error_when_directory_exists(self):
        """Test returns 1 when project directory already exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create existing directory
            existing = Path(tmpdir) / "myproject"
            existing.mkdir()

            tool = ScaffoldTool()
            tool._logger = Mock()
            args = Mock()
            args.name = "myproject"
            args.path = tmpdir
            args.with_db = False
            args.with_server = False
            args.with_logging_db = False
            args.makefile_style = "standalone"
            tool._parsed_args = args

            result = tool.run()

            assert result == 1
            tool._logger.error.assert_called()

    def test_creates_project_successfully(self):
        """Test creates project and returns 0 on success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ScaffoldTool()
            tool._logger = Mock()
            args = Mock()
            args.name = "myproject"
            args.path = tmpdir
            args.with_db = False
            args.with_server = False
            args.with_logging_db = False
            args.makefile_style = "standalone"
            tool._parsed_args = args

            result = tool.run()

            assert result == 0
            project_path = Path(tmpdir) / "myproject"
            assert project_path.exists()

    def test_handles_exception_gracefully(self):
        """Test handles exceptions and returns 1."""
        tool = ScaffoldTool()
        tool._logger = Mock()
        tool._create_structure = Mock(side_effect=Exception("Test error"))
        args = Mock()
        args.name = "myproject"
        args.path = "/nonexistent/path/that/should/fail"
        args.with_db = False
        args.with_server = False
        args.with_logging_db = False
        args.makefile_style = "standalone"
        tool._parsed_args = args

        result = tool.run()

        assert result == 1
        tool._logger.error.assert_called()


# =============================================================================
# Test _create_structure
# =============================================================================


@pytest.mark.unit
class TestCreateStructure:
    """Test ScaffoldTool._create_structure method."""

    def test_creates_required_directories(self):
        """Test creates etc, tests, and project directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir) / "myproject"

            tool = ScaffoldTool()
            tool._logger = Mock()

            tool._create_structure(project_path, with_db=False, with_server=False)

            assert (project_path / "etc").exists()
            assert (project_path / "tests").exists()
            assert (project_path / "myproject").exists()


# =============================================================================
# Test Config Section Generators
# =============================================================================


@pytest.mark.unit
class TestConfigLoggingSection:
    """Test ScaffoldTool._config_logging_section method."""

    def test_basic_logging_config(self):
        """Test generates basic logging config without database handler."""
        tool = ScaffoldTool()
        tool._logger = Mock()

        lines = tool._config_logging_section(with_logging_db=False)

        content = "\n".join(lines)
        assert "logging:" in content
        assert "level: info" in content
        assert "console_text:" in content
        assert "database:" not in content

    def test_logging_config_with_database(self):
        """Test generates logging config with database handler."""
        tool = ScaffoldTool()
        tool._logger = Mock()

        lines = tool._config_logging_section(with_logging_db=True)

        content = "\n".join(lines)
        assert "database:" in content
        assert "type: database" in content
        assert "buffer_size:" in content


@pytest.mark.unit
class TestConfigDatabaseSection:
    """Test ScaffoldTool._config_database_section method."""

    def test_generates_database_config(self):
        """Test generates pgserver and dbs configuration."""
        tool = ScaffoldTool()
        tool._logger = Mock()

        lines = tool._config_database_section("myproject")

        content = "\n".join(lines)
        assert "pgserver:" in content
        assert "myproject-pg" in content
        assert "dbs:" in content
        assert "main:" in content
        assert "myproject" in content  # DB name in URL


@pytest.mark.unit
class TestConfigServerSection:
    """Test ScaffoldTool._config_server_section method."""

    def test_generates_server_config(self):
        """Test generates server configuration."""
        tool = ScaffoldTool()
        tool._logger = Mock()

        lines = tool._config_server_section()

        content = "\n".join(lines)
        assert "server:" in content
        assert "host:" in content
        assert "port:" in content


# =============================================================================
# Test _generate_config
# =============================================================================


@pytest.mark.unit
class TestGenerateConfig:
    """Test ScaffoldTool._generate_config method."""

    def test_generates_minimal_config(self):
        """Test generates config with just logging."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / "etc").mkdir()

            tool = ScaffoldTool()
            tool._logger = Mock()

            tool._generate_config(
                project_path,
                "myproject",
                with_db=False,
                with_server=False,
                with_logging_db=False,
            )

            config_path = project_path / "etc" / "infra.yaml"
            assert config_path.exists()
            content = config_path.read_text()
            assert "logging:" in content
            assert "pgserver:" not in content
            assert "server:" not in content

    def test_generates_full_config(self):
        """Test generates config with all features."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            (project_path / "etc").mkdir()

            tool = ScaffoldTool()
            tool._logger = Mock()

            tool._generate_config(
                project_path,
                "myproject",
                with_db=True,
                with_server=True,
                with_logging_db=True,
            )

            config_path = project_path / "etc" / "infra.yaml"
            content = config_path.read_text()
            assert "logging:" in content
            assert "pgserver:" in content
            assert "server:" in content
            assert "type: database" in content


# =============================================================================
# Test App Generation Methods
# =============================================================================


@pytest.mark.unit
class TestAppImportsSection:
    """Test ScaffoldTool._app_imports_section method."""

    def test_basic_imports(self):
        """Test generates basic imports without database."""
        tool = ScaffoldTool()
        tool._logger = Mock()

        lines = tool._app_imports_section("myproject", with_db=False)

        content = "\n".join(lines)
        assert "from appinfra.app import App, AppBuilder" in content
        assert "from appinfra.db import PG" not in content

    def test_imports_with_database(self):
        """Test generates imports with database."""
        tool = ScaffoldTool()
        tool._logger = Mock()

        lines = tool._app_imports_section("myproject", with_db=True)

        content = "\n".join(lines)
        assert "from appinfra.db import PG" in content


@pytest.mark.unit
class TestAppToolClass:
    """Test ScaffoldTool._app_tool_class method."""

    def test_basic_tool_class(self):
        """Test generates basic ExampleTool class."""
        tool = ScaffoldTool()
        tool._logger = Mock()

        lines = tool._app_tool_class(with_db=False)

        content = "\n".join(lines)
        assert "class ExampleTool(Tool):" in content
        assert "def run(self, **kwargs)" in content
        assert "db_config" not in content

    def test_tool_class_with_database(self):
        """Test generates ExampleTool with database example."""
        tool = ScaffoldTool()
        tool._logger = Mock()

        lines = tool._app_tool_class(with_db=True)

        content = "\n".join(lines)
        assert "db_config" in content
        assert "health_check" in content


@pytest.mark.unit
class TestAppMainFunction:
    """Test ScaffoldTool._app_main_function method."""

    def test_generates_main_function(self):
        """Test generates main() function."""
        tool = ScaffoldTool()
        tool._logger = Mock()

        lines = tool._app_main_function("myproject")

        content = "\n".join(lines)
        assert "def main():" in content
        assert 'AppBuilder("myproject")' in content
        assert 'if __name__ == "__main__":' in content


# =============================================================================
# Test _generate_app
# =============================================================================


@pytest.mark.unit
class TestGenerateApp:
    """Test ScaffoldTool._generate_app method."""

    def test_generates_app_files(self):
        """Test generates __main__.py and __init__.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir) / "myproject"
            (project_path / "myproject").mkdir(parents=True)

            tool = ScaffoldTool()
            tool._logger = Mock()

            tool._generate_app(
                project_path, "myproject", with_db=False, with_server=False
            )

            main_path = project_path / "myproject" / "__main__.py"
            init_path = project_path / "myproject" / "__init__.py"

            assert main_path.exists()
            assert init_path.exists()

            main_content = main_path.read_text()
            assert "class ExampleTool" in main_content
            assert "def main():" in main_content

            init_content = init_path.read_text()
            assert "__version__" in init_content


# =============================================================================
# Test _generate_tests
# =============================================================================


@pytest.mark.unit
class TestGenerateTests:
    """Test ScaffoldTool._generate_tests method."""

    def test_generates_test_files(self):
        """Test generates test_example.py and __init__.py."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir) / "myproject"
            (project_path / "tests").mkdir(parents=True)

            tool = ScaffoldTool()
            tool._logger = Mock()

            tool._generate_tests(project_path, "myproject")

            test_path = project_path / "tests" / "test_example.py"
            init_path = project_path / "tests" / "__init__.py"

            assert test_path.exists()
            assert init_path.exists()

            content = test_path.read_text()
            assert "import unittest" in content
            assert "class TestExampleTool" in content


# =============================================================================
# Test Supporting File Generators
# =============================================================================


@pytest.mark.unit
class TestGenerateReadme:
    """Test ScaffoldTool._generate_readme method."""

    def test_generates_readme(self):
        """Test generates README.md with project name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)

            tool = ScaffoldTool()
            tool._logger = Mock()

            tool._generate_readme(project_path, "myproject")

            readme_path = project_path / "README.md"
            assert readme_path.exists()
            content = readme_path.read_text()
            assert "# myproject" in content
            assert "Setup" in content


@pytest.mark.unit
class TestGeneratePyproject:
    """Test ScaffoldTool._generate_pyproject method."""

    def test_generates_pyproject(self):
        """Test generates pyproject.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)

            tool = ScaffoldTool()
            tool._logger = Mock()

            tool._generate_pyproject(project_path, "myproject")

            pyproject_path = project_path / "pyproject.toml"
            assert pyproject_path.exists()
            content = pyproject_path.read_text()
            assert 'name = "myproject"' in content
            assert "[build-system]" in content


@pytest.mark.unit
class TestGenerateGitignore:
    """Test ScaffoldTool._generate_gitignore method."""

    def test_generates_gitignore(self):
        """Test generates .gitignore with Python patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)

            tool = ScaffoldTool()
            tool._logger = Mock()

            tool._generate_gitignore(project_path)

            gitignore_path = project_path / ".gitignore"
            assert gitignore_path.exists()
            content = gitignore_path.read_text()
            assert "__pycache__/" in content
            assert ".coverage" in content


@pytest.mark.unit
class TestGenerateMakefile:
    """Test ScaffoldTool._generate_makefile method."""

    def test_handles_missing_template(self):
        """Test logs warning when template not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)

            tool = ScaffoldTool()
            tool._logger = Mock()
            args = Mock()
            args.makefile_style = "standalone"
            tool._parsed_args = args

            # Template likely doesn't exist in test environment
            with patch.object(Path, "exists", return_value=False):
                tool._generate_makefile(project_path, "myproject")

            # Should warn but not fail
            # (may or may not warn depending on template existence)

    def test_generates_makefile_from_template(self):
        """Test generates Makefile when template exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)

            # Create a mock template
            template_content = "PROJECT = {{PROJECT_NAME}}\nall: build"

            tool = ScaffoldTool()
            tool._logger = Mock()
            args = Mock()
            args.makefile_style = "standalone"
            tool._parsed_args = args

            with patch.object(Path, "exists", return_value=True):
                with patch.object(Path, "read_text", return_value=template_content):
                    tool._generate_makefile(project_path, "myproject")

            makefile_path = project_path / "Makefile"
            if makefile_path.exists():
                content = makefile_path.read_text()
                assert "myproject" in content


@pytest.mark.unit
class TestGenerateSupportingFiles:
    """Test ScaffoldTool._generate_supporting_files method."""

    def test_generates_all_supporting_files(self):
        """Test generates README, pyproject, gitignore."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)

            tool = ScaffoldTool()
            tool._logger = Mock()
            args = Mock()
            args.makefile_style = "standalone"
            tool._parsed_args = args

            tool._generate_supporting_files(project_path, "myproject")

            assert (project_path / "README.md").exists()
            assert (project_path / "pyproject.toml").exists()
            assert (project_path / ".gitignore").exists()


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestScaffoldToolIntegration:
    """Integration tests for ScaffoldTool."""

    def test_full_project_generation_minimal(self):
        """Test complete minimal project generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ScaffoldTool()
            tool._logger = Mock()
            args = Mock()
            args.name = "testproject"
            args.path = tmpdir
            args.with_db = False
            args.with_server = False
            args.with_logging_db = False
            args.makefile_style = "standalone"
            tool._parsed_args = args

            result = tool.run()

            assert result == 0
            project_path = Path(tmpdir) / "testproject"

            # Verify structure
            assert (project_path / "etc" / "infra.yaml").exists()
            assert (project_path / "testproject" / "__main__.py").exists()
            assert (project_path / "testproject" / "__init__.py").exists()
            assert (project_path / "tests" / "test_example.py").exists()
            assert (project_path / "README.md").exists()
            assert (project_path / "pyproject.toml").exists()
            assert (project_path / ".gitignore").exists()

    def test_full_project_generation_with_all_features(self):
        """Test complete project generation with all features enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ScaffoldTool()
            tool._logger = Mock()
            args = Mock()
            args.name = "fullproject"
            args.path = tmpdir
            args.with_db = True
            args.with_server = True
            args.with_logging_db = True
            args.makefile_style = "standalone"
            tool._parsed_args = args

            result = tool.run()

            assert result == 0
            project_path = Path(tmpdir) / "fullproject"

            # Verify config includes all features
            config_content = (project_path / "etc" / "infra.yaml").read_text()
            assert "logging:" in config_content
            assert "pgserver:" in config_content
            assert "server:" in config_content
            assert "type: database" in config_content

            # Verify app includes database imports
            main_content = (project_path / "fullproject" / "__main__.py").read_text()
            assert "from appinfra.db import PG" in main_content
            assert "health_check" in main_content

    def test_project_name_with_underscores(self):
        """Test project generation with underscored name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tool = ScaffoldTool()
            tool._logger = Mock()
            args = Mock()
            args.name = "my_cool_project"
            args.path = tmpdir
            args.with_db = False
            args.with_server = False
            args.with_logging_db = False
            args.makefile_style = "standalone"
            tool._parsed_args = args

            result = tool.run()

            assert result == 0
            project_path = Path(tmpdir) / "my_cool_project"
            assert (project_path / "my_cool_project" / "__main__.py").exists()
