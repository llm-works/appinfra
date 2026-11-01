#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run: greet
# ci-run: --etc-dir appinfra/examples/04_configuration/etc greet

"""
The etc directory next to the script, overridable with --etc-dir

Demonstrates the pattern for apps that:
- Ship their YAML in an etc/ directory beside the script.
- Let the operator point at another directory with `--etc-dir`.
- Need the etc directory inside `Tool.configure()`.

The config spec locates etc/etc_dir_only_greeter.yaml beside this script, from
whatever directory the script runs in. `--etc-dir` replaces that directory; the
framework validates it during `app.setup()` (after parse_args, before any
`Tool.setup()` runs). Either way the directory is exposed on `app.etc_dir`, so
the tool never reads `args.etc_dir` itself.

Running:
    ~/.venv/bin/python examples/04_configuration/etc_dir_only_example.py greet
    ~/.venv/bin/python examples/04_configuration/etc_dir_only_example.py \\
        --etc-dir examples/04_configuration/etc greet

Key points:
- `.config.with_spec(...)` with no origin anchors on this script's directory.
- `.cli(etc_dir=True)` adds the `--etc-dir` override.
- Read `self.app.etc_dir` inside `Tool.configure()` — populated by the framework.
- A bad `--etc-dir /missing` raises `FileNotFoundError` at setup (fail-fast).
"""

from __future__ import annotations

import pathlib
import sys
from pathlib import Path
from typing import Any

import yaml

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

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
        """Load YAML from the etc directory the framework validated."""
        etc_dir = self.app.etc_dir
        if etc_dir is None:
            raise RuntimeError("app.etc_dir is None; pass --etc-dir <dir>")

        config_path = pathlib.Path(etc_dir) / "etc_dir_only_greeter.yaml"
        try:
            with open(config_path) as f:
                settings = yaml.safe_load(f)
        except FileNotFoundError as e:
            raise RuntimeError(
                f"etc_dir_only_greeter.yaml not found in {etc_dir}; "
                "pass --etc-dir <dir-containing-the-yaml>"
            ) from e

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
        # No module is named after the config, so its base is located beside
        # this script: ./etc/etc_dir_only_greeter.yaml.
        .config.with_spec(
            "example-org", "etc-dir-only-demo", filename="etc_dir_only_greeter.yaml"
        )
        .done()
        .cli(etc_dir=True)
        .tools.with_tool(GreetTool())
        .done()
        .logging.with_level("warning")
        .done()
        .build()
    )
    return app.main()


if __name__ == "__main__":
    sys.exit(main())
