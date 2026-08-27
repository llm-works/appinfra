# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Project health check tool for the appinfra CLI.

Diagnoses project configuration, dependencies, and environment setup,
providing actionable suggestions for any issues found.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable


@dataclass
class CheckResult:
    """Result of a single health check."""

    name: str
    passed: bool
    message: str
    suggestion: str | None = None


class DoctorTool(Tool):
    """
    CLI tool for checking project health and configuration.

    Performs checks for:
    - Python version compatibility
    - Required tools (ruff, pytest, mypy)
    - Package configuration (INFRA_DEV_PKG_NAME validity)
    - Project structure (tests/ directory)
    - Config file syntax (Makefile.local)
    """

    def __init__(self, parent: Traceable | None = None):
        """Initialize the doctor tool."""
        config = ToolConfig(
            name="doctor",
            aliases=["dr"],
            help_text="Check project health and configuration",
            description=(
                "Run diagnostic checks on your project setup. "
                "Validates Python version, required tools, package configuration, "
                "and project structure."
            ),
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
        """Add command-line arguments."""
        parser.add_argument(
            "--pkg-name",
            default=None,
            help="Package name to validate (default: from INFRA_DEV_PKG_NAME env var)",
        )
        parser.add_argument(
            "--project-root",
            default=".",
            help="Project root directory (default: current directory)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output results as JSON",
        )

    def run(self, **kwargs: Any) -> int:
        """Execute health checks."""
        results: list[CheckResult] = []

        # Run all checks
        results.append(self._check_python_version())
        results.extend(self._check_required_tools())
        results.append(self._check_package_name())
        results.append(self._check_tests_directory())
        results.append(self._check_config_syntax())

        # Output results
        if getattr(self.args, "json", False):
            return self._output_json(results)
        else:
            return self._output_pretty(results)

    def _check_python_version(self) -> CheckResult:
        """Check Python version >= 3.11."""
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"

        if version >= (3, 11):
            return CheckResult(
                name="Python version",
                passed=True,
                message=f"{version_str} (>= 3.11 required)",
            )
        else:
            return CheckResult(
                name="Python version",
                passed=False,
                message=f"{version_str} (>= 3.11 required)",
                suggestion="Upgrade to Python 3.11 or later",
            )

    def _check_required_tools(self) -> list[CheckResult]:
        """Check for ruff, pytest, mypy."""
        tools = [
            ("ruff", "ruff", "pip install ruff"),
            ("pytest", "pytest", "pip install pytest pytest-xdist pytest-cov"),
            ("mypy", "mypy", "pip install mypy"),
        ]
        return [
            self._check_single_tool(name, module, hint) for name, module, hint in tools
        ]

    def _check_single_tool(
        self, name: str, module: str, install_hint: str
    ) -> CheckResult:
        """Check if a single tool is installed and get its version."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", module, "--version"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                output = result.stdout.decode().strip()
                version = self._extract_version(output)
                return CheckResult(name=name, passed=True, message=version)
            return CheckResult(
                name=name,
                passed=False,
                message="not installed",
                suggestion=install_hint,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return CheckResult(
                name=name,
                passed=False,
                message="not installed",
                suggestion=install_hint,
            )
        except Exception:
            return CheckResult(
                name=name, passed=False, message="check failed", suggestion=install_hint
            )

    def _extract_version(self, output: str) -> str:
        """Extract version number from tool output."""
        import re

        if not output:
            return "installed"

        # Try to find a version pattern (e.g., "1.19.0", "0.14.7")
        match = re.search(r"\d+\.\d+\.?\d*", output)
        if match:
            return match.group()

        # Fallback: second token (e.g., "mypy 1.19.0" -> "1.19.0")
        parts = output.split()
        if len(parts) >= 2:
            return parts[1]

        return "installed"

    def _check_package_name(self) -> CheckResult:
        """Validate INFRA_DEV_PKG_NAME."""
        pkg_name = getattr(self.args, "pkg_name", None) or os.environ.get(
            "INFRA_DEV_PKG_NAME"
        )
        if not pkg_name:
            return CheckResult(
                name="Package name",
                passed=False,
                message="INFRA_DEV_PKG_NAME not set",
                suggestion="Set INFRA_DEV_PKG_NAME in your Makefile or environment",
            )

        project_root = Path(getattr(self.args, "project_root", "."))
        return self._validate_package_structure(pkg_name, project_root)

    def _validate_package_structure(
        self, pkg_name: str, project_root: Path
    ) -> CheckResult:
        """Validate that package directory exists and is a valid Python package."""
        pkg_dir = project_root / pkg_name

        if not pkg_dir.exists():
            return CheckResult(
                name="Package name",
                passed=False,
                message=f"Directory '{pkg_name}/' does not exist",
                suggestion=f"Create {pkg_name}/ directory or fix INFRA_DEV_PKG_NAME",
            )

        if not (pkg_dir / "__init__.py").exists():
            return CheckResult(
                name="Package name",
                passed=False,
                message=f"'{pkg_name}/__init__.py' missing",
                suggestion=f"Create {pkg_name}/__init__.py",
            )

        return CheckResult(
            name="Package name",
            passed=True,
            message=f"'{pkg_name}/' is valid Python package",
        )

    def _check_tests_directory(self) -> CheckResult:
        """Check tests/ directory exists and has content."""
        project_root = Path(getattr(self.args, "project_root", "."))
        tests_dir = project_root / "tests"

        if not tests_dir.exists():
            return CheckResult(
                name="Tests directory",
                passed=False,
                message="tests/ directory not found",
                suggestion="Create tests/ directory with test files",
            )

        # Check for test files (recursively)
        test_files = list(tests_dir.rglob("test_*.py"))
        if not test_files:
            return CheckResult(
                name="Tests directory",
                passed=False,
                message="tests/ exists but has no test files",
                suggestion="Add test files (e.g., tests/test_example.py)",
            )

        return CheckResult(
            name="Tests directory",
            passed=True,
            message=f"{len(test_files)} test files found",
        )

    def _check_config_syntax(self) -> CheckResult:
        """Validate Makefile.local syntax if present."""
        project_root = Path(getattr(self.args, "project_root", "."))
        config_file = self._find_config_file(project_root)

        if not config_file:
            return CheckResult(
                name="Config file",
                passed=True,
                message="no Makefile.local found (using defaults)",
            )

        if not shutil.which("make"):
            return CheckResult(
                name="Config file",
                passed=True,
                message=f"{config_file.name} found (make not available for validation)",
            )

        return self._validate_config_with_make(config_file, project_root)

    def _find_config_file(self, project_root: Path) -> Path | None:
        """Search for Makefile.local config file."""
        config_file = project_root / "Makefile.local"
        return config_file if config_file.exists() else None

    def _validate_config_with_make(
        self, config_file: Path, project_root: Path
    ) -> CheckResult:
        """Validate Makefile syntax using make --dry-run."""
        try:
            result = subprocess.run(
                ["make", "-n", "-f", str(config_file), "--warn-undefined-variables"],
                capture_output=True,
                timeout=5,
                cwd=str(project_root),
            )
            return self._parse_make_validation_result(result, config_file)
        except subprocess.TimeoutExpired:
            return CheckResult(
                name="Config file",
                passed=True,
                message=f"{config_file.name} found (validation timed out)",
            )
        except Exception as e:
            return CheckResult(
                name="Config file",
                passed=False,
                message=f"could not validate {config_file.name}",
                suggestion=str(e)[:80],
            )

    def _parse_make_validation_result(
        self, result: subprocess.CompletedProcess[bytes], config_file: Path
    ) -> CheckResult:
        """Parse make validation output for errors."""
        stderr = result.stderr.decode().strip()
        if "error" in stderr.lower() or "missing separator" in stderr.lower():
            return CheckResult(
                name="Config file",
                passed=False,
                message=f"syntax error in {config_file.name}",
                suggestion=f"Check syntax: {stderr[:80]}",
            )
        return CheckResult(
            name="Config file",
            passed=True,
            message=f"{config_file.name} syntax valid",
        )

    def _output_pretty(self, results: list[CheckResult]) -> int:
        """Output with checkmarks/X marks."""
        print("Project Health Check")
        print("=" * 40)
        print()

        all_passed = True
        for result in results:
            if result.passed:
                status = "[ok]"
            else:
                status = "[X] "
                all_passed = False

            print(f"{status} {result.name}: {result.message}")

            if result.suggestion:
                print(f"     -> {result.suggestion}")

        print()
        if all_passed:
            print("All checks passed!")
            return 0
        else:
            print("Some checks failed. See suggestions above.")
            return 1

    def _output_json(self, results: list[CheckResult]) -> int:
        """Output as JSON."""
        import json

        all_passed = all(r.passed for r in results)
        output = {
            "passed": all_passed,
            "checks": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "message": r.message,
                    "suggestion": r.suggestion,
                }
                for r in results
            ],
        }
        print(json.dumps(output, indent=2))
        return 0 if all_passed else 1
