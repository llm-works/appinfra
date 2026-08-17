"""
Project scaffolding generator tool.

This tool generates a complete project structure for infra-based applications.
"""

from pathlib import Path
from typing import Any

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable

# Helper functions for ScaffoldTool.run()


def _report_error_to_stderr(lg: Any, message: str) -> None:
    """Report error via logger and stderr (for test capture)."""
    lg.error(message)
    # Also write to stderr for CLI error reporting (tests capture this)
    import sys

    sys.stderr.write(f"ERROR: {message}\n")


def _extract_scaffold_arguments(args: Any) -> tuple[str, str, bool, bool, bool, str]:
    """Extract scaffold arguments from parsed args namespace."""
    return (
        args.name,
        getattr(args, "path", "."),
        getattr(args, "with_db", False),
        getattr(args, "with_server", False),
        getattr(args, "with_logging_db", False),
        getattr(args, "makefile_style", "standalone"),
    )


def _log_next_steps(lg: Any, name: str, project_path: Path) -> None:
    """Log next steps after project creation."""
    lg.info("project created successfully!", extra={"path": str(project_path)})
    lg.info("\nNext steps:")
    lg.info(f"  cd {name}")
    lg.info(f"  ~/.venv/bin/python -m {name}")


class ScaffoldTool(Tool):
    """
    Tool for generating project scaffolding.

    Creates a complete project structure with configuration, example code,
    and test setup.
    """

    def __init__(self, parent: Traceable | None = None):
        """Initialize the scaffold tool."""
        config = ToolConfig(
            name="scaffold",
            help_text="Generate project scaffolding for infra-based applications",
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
        """Add command-line arguments."""
        parser.add_argument("name", help="Project name")
        parser.add_argument(
            "--path",
            default=".",
            help="Path where project should be created (default: current directory)",
        )
        parser.add_argument(
            "--with-db",
            action="store_true",
            help="Include database configuration and examples",
        )
        parser.add_argument(
            "--with-server",
            action="store_true",
            help="Include HTTP server configuration and examples",
        )
        parser.add_argument(
            "--with-logging-db",
            action="store_true",
            help="Include database logging handler configuration",
        )
        parser.add_argument(
            "--makefile-style",
            choices=["standalone", "framework"],
            default="standalone",
            help="Makefile style: standalone (self-contained) or framework (includes infra components)",
        )

    def run(self, **kwargs: Any) -> int:
        """
        Generate project scaffolding.

        Args:
            **kwargs: Arguments from argparse

        Returns:
            Exit code (0 for success)
        """
        name, path, with_db, with_server, with_logging_db, makefile_style = (
            _extract_scaffold_arguments(self.args)
        )

        # Validate inputs
        validation_error = self._validate_inputs(name, path)
        if validation_error:
            _report_error_to_stderr(self.lg, validation_error)  # type: ignore[union-attr]
            return 1

        # Generate project
        project_path = Path(path) / name
        return self._generate_project(
            project_path, name, with_db, with_server, with_logging_db, makefile_style
        )

    def _validate_inputs(self, name: str, path: str) -> str | None:
        """Validate project name and path. Returns error message or None."""
        if not self._is_valid_project_name(name):
            return (
                f"Invalid project name: {name}. "
                "Must contain only letters, numbers, underscores, and hyphens."
            )
        project_path = Path(path) / name
        if project_path.exists():
            return f"Directory already exists: {project_path}"
        return None

    def _generate_project(
        self,
        project_path: Path,
        name: str,
        with_db: bool,
        with_server: bool,
        with_logging_db: bool,
        makefile_style: str,
    ) -> int:
        """Generate project structure and files."""
        self.lg.info(f"Creating project: {name}", extra={"path": str(project_path)})  # type: ignore[union-attr]

        try:
            self._create_structure(project_path, with_db, with_server)
            self._generate_config(
                project_path, name, with_db, with_server, with_logging_db
            )
            self._generate_app(project_path, name, with_db, with_server)
            self._generate_tests(project_path, name)
            self._generate_supporting_files(project_path, name)

            _log_next_steps(self.lg, name, project_path)
            return 0
        except Exception as e:
            self.lg.error("failed to create project", extra={"exception": e})  # type: ignore[union-attr]
            return 1

    def _is_valid_project_name(self, name: str) -> bool:
        """
        Validate project name contains only safe characters.

        Args:
            name: Project name to validate

        Returns:
            True if name is valid, False otherwise
        """
        import re

        # Allow letters, numbers, underscores, hyphens
        # Must start with letter or underscore
        pattern = r"^[a-zA-Z_][a-zA-Z0-9_-]*$"
        return bool(re.match(pattern, name))

    def _create_structure(
        self, project_path: Path, with_db: bool, with_server: bool
    ) -> None:
        """Create project directory structure."""
        # Main directories
        (project_path / "etc").mkdir(parents=True)
        (project_path / "tests").mkdir(parents=True)
        (project_path / project_path.name).mkdir(parents=True)

        self.lg.debug("created directory structure")  # type: ignore[union-attr]

    def _config_logging_section(self, with_logging_db: bool) -> list[str]:
        """Generate logging configuration section."""
        lines = [
            "logging:",
            "  level: info",
            "  location: false",
            "  micros: false",
            "  handlers:",
            "    console_text:",
            "      type: console",
            "      level: info",
        ]

        if with_logging_db:
            lines.extend(
                [
                    "",
                    "    database:",
                    "      type: database",
                    "      level: warning",
                    "      table: logs",
                    "      buffer_size: 100",
                    "      flush_interval: 5.0",
                    "      flush_level: critical",
                ]
            )

        return lines

    def _config_database_section(self, name: str) -> list[str]:
        """Generate database configuration section."""
        return [
            "",
            "pgserver:",
            "  version: 18",
            "  name: " + name + "-pg",
            "  port: 5432",
            "  user: postgres",
            "  pass: ''",
            "",
            "dbs:",
            "  main:",
            "    url: postgresql://postgres@localhost:5432/" + name,
            "    pool_size: 5",
            "    max_overflow: 10",
            "    readonly: false",
            "    create_db: false",
            "    auto_reconnect: true",
            "    max_retries: 3",
            "    retry_delay: 1.0",
        ]

    def _config_server_section(self) -> list[str]:
        """Generate server configuration section."""
        return [
            "",
            "server:",
            "  host: localhost",
            "  port: 8080",
            "  workers: 4",
        ]

    def _generate_config(
        self,
        project_path: Path,
        name: str,
        with_db: bool,
        with_server: bool,
        with_logging_db: bool,
    ) -> None:
        """Generate configuration file."""
        config_lines = ["# Configuration for " + name, ""]
        config_lines.extend(self._config_logging_section(with_logging_db))

        if with_db:
            config_lines.extend(self._config_database_section(name))
        if with_server:
            config_lines.extend(self._config_server_section())

        config_path = project_path / "etc" / "infra.yaml"
        config_path.write_text("\n".join(config_lines) + "\n")
        self.lg.debug(f"Generated config: {config_path}")  # type: ignore[union-attr]

    def _app_imports_section(self, name: str, with_db: bool) -> list[str]:
        """Generate imports section for app file."""
        lines = [
            '"""',
            f"{name} - Application entry point",
            '"""',
            "",
            "from appinfra.app import App, AppBuilder",
            "from appinfra.config import Config",
            "from appinfra.app.tools import Tool, ToolConfig",
        ]
        if with_db:
            lines.append("from appinfra.db import PG")
        return lines

    def _app_tool_class(self, with_db: bool) -> list[str]:
        """Generate ExampleTool class for app file."""
        lines = [
            "",
            "",
            "class ExampleTool(Tool):",
            '    """Example tool implementation."""',
            "",
            "    def __init__(self, parent=None):",
            '        config = ToolConfig(name="example", help_text="Example tool")',
            "        super().__init__(parent, config)",
            "",
            "    def run(self, **kwargs) -> int:",
            '        """Run the example tool."""',
            '        self.lg.info("Running example tool!")',
        ]

        if with_db:
            lines.extend(
                [
                    "        # Database example",
                    "        db_config = self.parent.config.dbs.main",
                    "        db = PG(self.lg, db_config)",
                    "        health = db.health_check()",
                    "        self.lg.info(f\"Database health: {health['status']}\")",
                ]
            )

        lines.append("        return 0")
        return lines

    def _app_main_function(self, name: str) -> list[str]:
        """Generate main() function for app file."""
        return [
            "",
            "",
            "def main():",
            '    """Main entry point."""',
            "    # Load configuration",
            '    config = Config("etc/infra.yaml")',
            "",
            "    # Build application",
            "    app = (",
            '        AppBuilder("' + name + '")',
            "        .with_config(config)",
            "        .logging",
            "            .with_level(config.logging.level)",
            "            .done()",
            "        .tools",
            "            .with_tool(ExampleTool())",
            "            .done()",
            "        .build()",
            "    )",
            "",
            "    # Run application",
            "    return app.main()",
            "",
            "",
            'if __name__ == "__main__":',
            "    exit(main())",
        ]

    def _generate_app(
        self, project_path: Path, name: str, with_db: bool, with_server: bool
    ) -> None:
        """Generate main application file."""
        app_lines = []
        app_lines.extend(self._app_imports_section(name, with_db))
        app_lines.extend(self._app_tool_class(with_db))
        app_lines.extend(self._app_main_function(name))

        app_path = project_path / project_path.name / "__main__.py"
        app_path.write_text("\n".join(app_lines) + "\n")

        # Create __init__.py
        init_path = project_path / project_path.name / "__init__.py"
        init_path.write_text(f'"""{name} package."""\n\n__version__ = "0.1.0"\n')

        self.lg.debug(f"Generated app: {app_path}")  # type: ignore[union-attr]

    def _generate_tests(self, project_path: Path, name: str) -> None:
        """Generate test files."""
        test_lines = [
            '"""',
            f"Tests for {name}",
            '"""',
            "",
            "import unittest",
            f"from {name}.__main__ import ExampleTool",
            "",
            "",
            "class TestExampleTool(unittest.TestCase):",
            '    """Test the example tool."""',
            "",
            "    def test_tool_creation(self):",
            '        """Test tool can be created."""',
            "        tool = ExampleTool()",
            '        self.assertEqual(tool.name, "example")',
            "",
            "",
            'if __name__ == "__main__":',
            "    unittest.main()",
        ]

        test_path = project_path / "tests" / "test_example.py"
        test_path.write_text("\n".join(test_lines) + "\n")

        # Create __init__.py for tests
        (project_path / "tests" / "__init__.py").write_text("")

        self.lg.debug(f"Generated tests: {test_path}")  # type: ignore[union-attr]

    def _generate_readme(self, project_path: Path, name: str) -> None:
        """Generate README.md file."""
        readme_lines = [
            f"# {name}",
            "",
            "Project generated with infra scaffolding tool.",
            "",
            "## Setup",
            "",
            "```bash",
            "# Install dependencies",
            "~/.venv/bin/pip install .",
            "```",
            "",
            "## Usage",
            "",
            "```bash",
            f"~/.venv/bin/python -m {name} example",
            "```",
            "",
            "## Development",
            "",
            "```bash",
            "# Run tests",
            "~/.venv/bin/python -m unittest discover tests",
            "```",
        ]
        (project_path / "README.md").write_text("\n".join(readme_lines) + "\n")

    def _generate_pyproject(self, project_path: Path, name: str) -> None:
        """Generate pyproject.toml file."""
        pyproject_lines = [
            "[build-system]",
            'requires = ["setuptools>=68.0", "wheel"]',
            'build-backend = "setuptools.build_meta"',
            "",
            "[project]",
            f'name = "{name}"',
            'version = "0.1.0"',
            f'description = "{name} - infra-based application"',
            'requires-python = ">=3.11"',
            "dependencies = [",
            '    "infra",',
            "]",
        ]
        (project_path / "pyproject.toml").write_text("\n".join(pyproject_lines) + "\n")

    def _generate_gitignore(self, project_path: Path) -> None:
        """Generate .gitignore file."""
        gitignore_lines = [
            "__pycache__/",
            "*.py[cod]",
            "*$py.class",
            "*.so",
            ".Python",
            "*.egg-info/",
            "dist/",
            "build/",
            ".coverage",
            ".pytest_cache/",
        ]
        (project_path / ".gitignore").write_text("\n".join(gitignore_lines) + "\n")

    def _generate_makefile(self, project_path: Path, name: str) -> None:
        """Generate Makefile from template."""
        makefile_style = getattr(self.args, "makefile_style", "standalone")

        # Choose template based on style
        template_name = (
            "Makefile.framework.in"
            if makefile_style == "framework"
            else "Makefile.standalone.in"
        )

        # Load template using importlib.resources
        try:
            import importlib.resources

            template_files = importlib.resources.files("appinfra.cli.tools.scaffold")
            template_path = template_files / template_name

            if not template_path.is_file():
                self.lg.warning(f"Template not found: {template_name}")  # type: ignore[union-attr]
                return

            template_content = template_path.read_text()
            makefile_content = template_content.replace("{{PROJECT_NAME}}", name)

            (project_path / "Makefile").write_text(makefile_content)
            self.lg.debug(f"Generated {makefile_style} Makefile")  # type: ignore[union-attr]

        except Exception as e:
            self.lg.error("failed to generate Makefile", extra={"exception": e})  # type: ignore[union-attr]

    def _generate_supporting_files(self, project_path: Path, name: str) -> None:
        """Generate README, pyproject.toml, etc."""
        self._generate_readme(project_path, name)
        self._generate_pyproject(project_path, name)
        self._generate_gitignore(project_path)
        self._generate_makefile(project_path, name)
        self.lg.debug("generated supporting files")  # type: ignore[union-attr]
