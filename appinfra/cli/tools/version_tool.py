# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Version information tool."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import appinfra

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable

if TYPE_CHECKING:
    from argparse import ArgumentParser

# Field subcommands
_FIELDS = ("semver", "commit", "full", "modified", "time", "message", "init-hook")


def _get_build_info() -> dict[str, Any]:
    """Get build info from installed package."""
    try:
        from ... import _build_info

        return {
            "commit": getattr(_build_info, "COMMIT_SHORT", "") or None,
            "full": getattr(_build_info, "COMMIT_HASH", "") or None,
            "message": getattr(_build_info, "COMMIT_MESSAGE", "") or None,
            "time": getattr(_build_info, "BUILD_TIME", "") or None,
            "modified": getattr(_build_info, "MODIFIED", None),
        }
    except ImportError:
        return {
            "commit": None,
            "full": None,
            "message": None,
            "time": None,
            "modified": None,
        }


class VersionTool(Tool):
    """Display version and build information."""

    def __init__(self, parent: Traceable | None = None):
        """Initialize the version tool."""
        config = ToolConfig(
            name="version",
            help_text="Show version and build info",
            description=(
                "Display version, commit hash, and build information. "
                "Use subcommands to extract specific fields for scripting."
            ),
        )
        super().__init__(parent, config)

    def add_args(self, parser: ArgumentParser) -> None:
        """Add command-line arguments."""
        self._add_positional_args(parser)
        self._add_optional_args(parser)

    def _add_positional_args(self, parser: ArgumentParser) -> None:
        """Add positional arguments (field, package)."""
        parser.add_argument(
            "field",
            nargs="?",
            choices=_FIELDS,
            help=(
                "Field to output: semver, commit, full, modified, time, message. "
                "Use 'init-hook' to generate a standalone setup.py for downstream projects."
            ),
        )
        parser.add_argument(
            "package", nargs="?", help="Package name (required for init-hook)"
        )

    def _add_optional_args(self, parser: ArgumentParser) -> None:
        """Add optional arguments (--json, --output, --with-stub)."""
        parser.add_argument(
            "--json", dest="as_json", action="store_true", help="Output as JSON"
        )
        parser.add_argument(
            "-o", "--output", dest="output_file", help="Write to file (init-hook)"
        )
        parser.add_argument(
            "--with-stub", action="store_true", dest="with_stub", help="Generate stub"
        )

    def run(self, **kwargs: Any) -> int:
        """Display version information."""
        field, as_json, package, output_file, with_stub = self._get_args(kwargs)

        if field == "init-hook":
            return self._handle_init_hook(package, output_file, with_stub)

        semver = appinfra.__version__
        build = _get_build_info()

        if as_json:
            return self._output_json(semver, build)
        if field:
            return self._output_field(field, semver, build)
        return self._output_default(semver, build)

    def _get_args(
        self, kwargs: dict[str, Any]
    ) -> tuple[str | None, bool, str | None, str | None, bool]:
        """Extract arguments from kwargs with fallback to parsed args."""
        field = kwargs.get("field")
        as_json = kwargs.get("as_json", False)
        package = kwargs.get("package")
        output_file = kwargs.get("output_file")
        with_stub = kwargs.get("with_stub", False)

        if hasattr(self, "_parsed_args") and self._parsed_args:
            if field is None:
                field = getattr(self._parsed_args, "field", None)
            if not as_json:
                as_json = getattr(self._parsed_args, "as_json", False)
            if package is None:
                package = getattr(self._parsed_args, "package", None)
            if output_file is None:
                output_file = getattr(self._parsed_args, "output_file", None)
            if not with_stub:
                with_stub = getattr(self._parsed_args, "with_stub", False)

        return field, as_json, package, output_file, with_stub

    def _output_json(self, semver: str, build: dict[str, Any]) -> int:
        """Output all fields as JSON."""
        data = {"semver": semver, **build}
        print(json.dumps(data, indent=2))
        return 0

    def _output_field(self, field: str, semver: str, build: dict[str, Any]) -> int:
        """Output a single field value."""
        if field == "semver":
            print(semver)
        elif field == "modified":
            value = build.get("modified")
            print("true" if value else "false" if value is False else "unknown")
        else:
            value = build.get(field)
            print(value if value else "")
        return 0

    def _output_default(self, semver: str, build: dict[str, Any]) -> int:
        """Output human-readable version string."""
        commit = build.get("commit")
        modified = build.get("modified")

        if commit:
            dirty = "*" if modified else ""
            print(f"appinfra {semver} ({commit}{dirty})")
        else:
            print(f"appinfra {semver}")
        return 0

    def _handle_init_hook(
        self, package: str | None, output_file: str | None, with_stub: bool
    ) -> int:
        """Handle init-hook subcommand to generate standalone setup.py."""
        error = self._validate_init_hook_args(package)
        if error:
            return error

        assert package is not None  # validated above
        self._generate_setup_py(package, output_file)

        if with_stub:
            self._generate_stub_file(package)

        return 0

    def _validate_init_hook_args(self, package: str | None) -> int | None:
        """Validate init-hook arguments. Returns error code or None if valid."""
        if not package:
            print("error: package name is required for init-hook", file=sys.stderr)
            print(
                "usage: appinfra version init-hook <package> [--output FILE]",
                file=sys.stderr,
            )
            return 1

        if not self._is_valid_package_name(package):
            print(f"error: invalid package name: {package}", file=sys.stderr)
            print(
                "Package name must contain only letters, numbers, and underscores",
                file=sys.stderr,
            )
            return 1

        return None

    def _generate_setup_py(self, package: str, output_file: str | None) -> None:
        """Generate setup.py content and write to file or stdout."""
        from ...version.setup_hook import generate_standalone_setup

        setup_content = generate_standalone_setup(package)

        if output_file:
            output_path = Path(output_file)
            output_path.write_text(setup_content)
            print(f"Generated {output_path}", file=sys.stderr)
        else:
            print(setup_content)

    def _generate_stub_file(self, package: str) -> None:
        """Generate stub _build_info.py file in package directory."""
        from ...version.setup_hook import get_stub_content

        stub_path = Path(package) / "_build_info.py"

        if not stub_path.parent.exists():
            print(
                f"warning: directory '{package}' does not exist, "
                "skipping _build_info.py stub",
                file=sys.stderr,
            )
        else:
            stub_path.write_text(get_stub_content())
            print(f"Generated {stub_path}", file=sys.stderr)

    def _is_valid_package_name(self, name: str) -> bool:
        """Validate package name contains only safe characters."""
        import re

        pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*$"
        return bool(re.match(pattern, name))
