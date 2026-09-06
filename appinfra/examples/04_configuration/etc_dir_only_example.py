#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run: --etc-dir appinfra/examples/04_configuration/etc greet

"""
--etc-dir without a config spec

Demonstrates the pattern for apps that:
- Opt into the `--etc-dir` CLI flag via `with_standard_args(etc_dir=True)`.
- Manage their own YAML files (no config spec declared).
- Need the etc directory inside `Tool.configure()`.

The framework validates `--etc-dir` during `app.setup()` (after parse_args, before
any `Tool.setup()` runs) and exposes it on `app.etc_dir`. There is no need to
read `args.etc_dir` from inside the tool or override the property.

Running:
    ~/.venv/bin/python examples/04_configuration/etc_dir_only_example.py \\
        --etc-dir examples/04_configuration/etc greet

Key points:
- `with_standard_args(etc_dir=True)` is the single opt-in.
- Read `self.app.etc_dir` inside `Tool.configure()` — populated by the framework.
- A bad `--etc-dir /missing` raises `FileNotFoundError` at setup (fail-fast).
- Without a spec there is no default directory: omit the flag and `app.etc_dir`
  is `None`. Apps that ship a config file declare a spec instead
  (`.config.with_spec(...)`), and `app.etc_dir` becomes the directory of the
  file the spec resolved to.
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
