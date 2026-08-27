# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
E2E test for scaffold tool workflow.

This test validates the complete workflow of project scaffolding,
including standalone and framework-based Makefile generation,
verifying generated files, and testing that the generated projects
work correctly.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


@pytest.mark.e2e
class TestScaffoldWorkflow:
    """
    E2E tests for scaffold tool workflow.

    Tests complete project generation with both standalone
    and framework-based Makefiles.
    """

    def setup_method(self):
        """Set up scaffold E2E test environment."""
        # Create temporary directory for test projects in /tmp
        self.temp_dir = Path(
            tempfile.mkdtemp(prefix="infra-scaffold-test-", dir="/tmp")
        )
        self.cli_path = project_root / "appinfra" / "cli" / "cli.py"
        self.infra_root = project_root

    def teardown_method(self):
        """Clean up after scaffold E2E test."""
        # Remove temporary directory with error handling
        try:
            if hasattr(self, "temp_dir") and self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            # Log but don't fail the test due to cleanup issues
            print(f"Warning: Failed to clean up {self.temp_dir}: {e}")

    def _create_fake_python_without_infra(self, project_path: Path) -> Path:
        """Create wrapper script that simulates Python without infra installed."""
        fake_python = project_path / "fake_python.sh"
        fake_python.write_text(
            "#!/bin/bash\n"
            "# Fail if trying to import appinfra\n"
            'if echo "$@" | grep -q "import appinfra"; then\n'
            "  exit 1\n"
            "fi\n"
            f'exec {sys.executable} "$@"\n'
        )
        fake_python.chmod(0o755)
        return fake_python

    def _run_scaffold(self, project_name: str, *args) -> subprocess.CompletedProcess:
        """
        Run scaffold command.

        Args:
            project_name: Name of project to scaffold
            *args: Additional arguments to scaffold command

        Returns:
            CompletedProcess result
        """
        cmd = [
            sys.executable,
            str(self.cli_path),
            "scaffold",
            project_name,
            "--path",
            str(self.temp_dir),
        ]
        cmd.extend(args)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.infra_root),
        )
        return result

    def _verify_directories(self, project_path: Path):
        """Verify project directories exist."""
        assert project_path.exists(), f"Project directory should exist: {project_path}"
        assert (project_path / "etc").exists(), "etc/ directory should exist"
        assert (project_path / "tests").exists(), "tests/ directory should exist"
        assert (project_path / project_path.name).exists(), (
            "Package directory should exist"
        )

    def _verify_config_files(self, project_path: Path):
        """Verify configuration files exist."""
        assert (project_path / "etc" / "infra.yaml").exists(), (
            "Configuration file should exist"
        )
        assert (project_path / "Makefile").exists(), "Makefile should exist"
        assert (project_path / "README.md").exists(), "README should exist"
        assert (project_path / "pyproject.toml").exists(), "pyproject.toml should exist"
        assert (project_path / ".gitignore").exists(), ".gitignore should exist"

    def _verify_package_structure(self, project_path: Path):
        """Verify Python package and test structure."""
        assert (project_path / project_path.name / "__init__.py").exists(), (
            "Package __init__.py should exist"
        )
        assert (project_path / project_path.name / "__main__.py").exists(), (
            "Package __main__.py should exist"
        )
        assert (project_path / "tests" / "__init__.py").exists(), (
            "Tests __init__.py should exist"
        )
        assert (project_path / "tests" / "test_example.py").exists(), (
            "Example test should exist"
        )

    def _verify_basic_structure(self, project_path: Path):
        """
        Verify basic project structure exists.

        Args:
            project_path: Path to generated project
        """
        self._verify_directories(project_path)
        self._verify_config_files(project_path)
        self._verify_package_structure(project_path)

    def test_standalone_scaffold_generation(self):
        """Test generating project with standalone Makefile."""
        project_name = "testapp_standalone"
        result = self._run_scaffold(project_name)

        # Verify scaffold command succeeded
        assert result.returncode == 0, (
            f"Scaffold should succeed. stderr: {result.stderr}"
        )

        project_path = self.temp_dir / project_name

        # Verify basic structure
        self._verify_basic_structure(project_path)

        # Verify standalone Makefile content
        makefile_content = (project_path / "Makefile").read_text()
        assert "PYTHON :=" in makefile_content  # Detection logic sets PYTHON
        assert "##@ General" in makefile_content
        assert "help:" in makefile_content
        assert "install:" in makefile_content
        assert "clean:" in makefile_content
        assert "test:" in makefile_content
        assert "INFRA_ROOT" not in makefile_content, (
            "Standalone should not reference INFRA_ROOT"
        )
        assert "COVERAGE_PKG" not in makefile_content, (
            "Standalone should not have COVERAGE_PKG"
        )

    def _verify_framework_makefile_content(
        self, makefile_content: str, project_name: str
    ):
        """Verify framework Makefile has expected content."""
        assert "Makefile.env" in makefile_content
        assert f"INFRA_DEV_PKG_NAME := {project_name}" in makefile_content
        assert "INFRA_ROOT" in makefile_content
        for makefile in [
            "Makefile.help",
            "Makefile.utils",
            "Makefile.clean",
            "Makefile.dev",
            "Makefile.pytest",
        ]:
            assert (
                f"include $(INFRA_ROOT)/scripts/make/{makefile}" in makefile_content
            ), f"Should include {makefile}"
        assert "run::" in makefile_content, "Should use double-colon rules"

    def test_framework_scaffold_generation(self):
        """Test generating project with framework-based Makefile."""
        project_name = "testapp_framework"
        result = self._run_scaffold(project_name, "--makefile-style=framework")

        assert result.returncode == 0, (
            f"Scaffold should succeed. stderr: {result.stderr}"
        )

        project_path = self.temp_dir / project_name
        self._verify_basic_structure(project_path)

        makefile_content = (project_path / "Makefile").read_text()
        self._verify_framework_makefile_content(makefile_content, project_name)

    def _verify_framework_targets(self, make_output: str):
        """Verify framework targets are available in make output."""
        assert "test.unit" in make_output, "Framework targets should be available"
        assert "test.coverage" in make_output
        assert "fmt" in make_output
        assert "lint" in make_output

    def test_standalone_makefile_help_works(self):
        """Test standalone Makefile help target works."""
        project_name = "testapp_help"
        result = self._run_scaffold(project_name)

        assert result.returncode == 0, (
            f"Scaffold should succeed. stderr: {result.stderr}"
        )

        project_path = self.temp_dir / project_name

        # Run make help
        make_result = subprocess.run(
            ["make", "help"],
            capture_output=True,
            text=True,
            cwd=str(project_path),
        )

        # Verify make help succeeded
        assert make_result.returncode == 0, (
            f"make help should succeed. stderr: {make_result.stderr}"
        )

        # Verify targets are listed
        assert "help" in make_result.stdout
        assert "install" in make_result.stdout
        assert "clean" in make_result.stdout
        assert "test" in make_result.stdout
        assert "run" in make_result.stdout

    def test_project_name_substitution(self):
        """Test that {{PROJECT_NAME}} is correctly replaced in all files."""
        project_name = "my_test_app"
        result = self._run_scaffold(project_name, "--makefile-style=framework")

        assert result.returncode == 0, (
            f"Scaffold should succeed. stderr: {result.stderr}"
        )

        project_path = self.temp_dir / project_name

        # Verify Makefile has project name
        makefile_content = (project_path / "Makefile").read_text()
        assert f"# {project_name} - Framework-based Makefile" in makefile_content
        assert f"INFRA_DEV_PKG_NAME := {project_name}" in makefile_content
        assert f"$(PYTHON) -m {project_name}" in makefile_content
        assert "{{PROJECT_NAME}}" not in makefile_content, (
            "Template variable should be replaced"
        )

        # Verify __main__.py has project name
        main_content = (project_path / project_name / "__main__.py").read_text()
        assert f'"{project_name}"' in main_content

        # Verify README has project name
        readme_content = (project_path / "README.md").read_text()
        assert f"# {project_name}" in readme_content
        assert f"python -m {project_name}" in readme_content

        # Verify pyproject.toml has project name
        pyproject_content = (project_path / "pyproject.toml").read_text()
        assert f'name = "{project_name}"' in pyproject_content

    def test_framework_makefile_error_without_infra(self):
        """Test framework Makefile shows error when infra not found."""
        project_name = "testapp_no_infra"
        result = self._run_scaffold(project_name, "--makefile-style=framework")

        assert result.returncode == 0, (
            f"Scaffold should succeed. stderr: {result.stderr}"
        )

        project_path = self.temp_dir / project_name

        # Create Python wrapper that simulates infra not being installed
        fake_python = self._create_fake_python_without_infra(project_path)

        # Try to run make help with Python that can't find infra
        make_result = subprocess.run(
            ["make", "help", f"PYTHON={fake_python}"],
            capture_output=True,
            text=True,
            cwd=str(project_path),
        )

        # Verify make failed with clear error
        assert make_result.returncode != 0, "make should fail when infra not found"
        assert "Cannot locate infra" in make_result.stderr, (
            "Should show clear error message"
        )

    def test_scaffold_with_database_option(self):
        """Test scaffolding with --with-db option."""
        project_name = "testapp_with_db"
        result = self._run_scaffold(project_name, "--with-db")

        assert result.returncode == 0, (
            f"Scaffold should succeed. stderr: {result.stderr}"
        )

        project_path = self.temp_dir / project_name

        # Verify database configuration exists
        config_content = (project_path / "etc" / "infra.yaml").read_text()
        assert "pgserver:" in config_content
        assert "dbs:" in config_content

        # Verify __main__.py has database imports
        main_content = (project_path / project_name / "__main__.py").read_text()
        assert "from appinfra.db import PG" in main_content
        assert "db_config" in main_content

    def test_multiple_projects_can_coexist(self):
        """Test that multiple scaffolded projects can exist side-by-side."""
        projects = ["app1", "app2", "app3"]

        for project_name in projects:
            result = self._run_scaffold(project_name)
            assert result.returncode == 0, f"Scaffold {project_name} should succeed"

        # Verify all projects exist
        for project_name in projects:
            project_path = self.temp_dir / project_name
            assert project_path.exists(), f"{project_name} should exist"
            assert (project_path / "Makefile").exists()

    def test_scaffold_overwrites_protection(self):
        """Test that scaffold refuses to overwrite existing directory."""
        project_name = "existing_project"

        # Create first time - should succeed
        result1 = self._run_scaffold(project_name)
        assert result1.returncode == 0, "First scaffold should succeed"

        # Try again - should fail
        result2 = self._run_scaffold(project_name)
        assert result2.returncode != 0, "Second scaffold should fail"
        assert "already exists" in result2.stdout + result2.stderr, (
            "Should mention directory exists"
        )
