#!/usr/bin/env python3
"""
etc_dir without with_config_file()

Demonstrates the recommended pattern for apps that:
- Opt into the `--etc-dir` CLI flag via `with_standard_args(etc_dir=True)`.
- Manage their own YAML files (no `with_config_file()` registration).
- Need the resolved etc directory inside `Tool.configure()`.

The framework resolves `etc_dir` during `app.setup()` (after parse_args, before
any `Tool.setup()` runs) and exposes the result on `app.etc_dir`. There is no
need to call `resolve_etc_dir()` from inside the tool, mutate args, or override
the property.

Running:
    # Uses the fallback chain (./etc next to the example, then project root)
    ~/.venv/bin/python examples/04_configuration/etc_dir_only_example.py greet

    # Or pass an explicit dir
    ~/.venv/bin/python examples/04_configuration/etc_dir_only_example.py \\
        --etc-dir examples/04_configuration/etc greet

Key points:
- `with_standard_args(etc_dir=True)` is the single opt-in; no `with_config_file()`.
- Read `self.app.etc_dir` inside `Tool.configure()` — populated by the framework.
- Explicit bad `--etc-dir /missing` raises `FileNotFoundError` at setup (fail-fast).
- Missing flag with no resolvable fallback yields `app.etc_dir is None`.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import yaml

project_root = str(pathlib.Path(__file__).resolve().parents[3])
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from appinfra.app.builder import AppBuilder
from appinfra.app.tools.base import Tool, ToolConfig


class GreetTool(Tool):
    """Loads its own YAML from app.etc_dir and prints a greeting."""

    def _create_config(self) -> ToolConfig:
        return ToolConfig(
            name="greet",
            help_text="Print a greeting loaded from etc_dir_only_greeter.yaml",
        )

    def configure(self) -> None:
        """Load YAML from the framework-resolved etc directory."""
        if self.app.etc_dir is None:
            # Only reachable if the user didn't pass --etc-dir AND no fallback
            # (./etc, project root, package etc) was found. Bail explicitly
            # rather than silently using a wrong default.
            raise RuntimeError(
                "no etc directory available; pass --etc-dir or run from a "
                "directory containing ./etc/etc_dir_only_greeter.yaml"
            )

        config_path = pathlib.Path(self.app.etc_dir) / "etc_dir_only_greeter.yaml"
        with open(config_path) as f:
            settings = yaml.safe_load(f)

        self._greeting = settings["greeting"]
        self._recipient = settings["recipient"]
        self._exclamations = int(settings.get("exclamations", 1))

    def run(self, **kwargs: Any) -> int:
        suffix = "!" * self._exclamations
        print(f"{self._greeting}, {self._recipient}{suffix}")
        print(f"(loaded from {self.app.etc_dir})")
        return 0


def main() -> int:
    app = (
        AppBuilder("etc-dir-only-demo")
        .with_description("Tool reads its own YAML from app.etc_dir")
        .with_standard_args(etc_dir=True)
        .tools.with_tool(GreetTool())
        .done()
        .logging.with_level("warning")
        .done()
        .build()
    )
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
