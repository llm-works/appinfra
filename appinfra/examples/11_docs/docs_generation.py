#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run: --help
# ci-run: status
# ci-run: generate

"""
Example: Auto-Generated Documentation

Demonstrates using DocsGenerator to create markdown documentation
from tool definitions. Documentation stays in sync with code because
it's generated from the actual tool configurations and argument parsers.

Usage:
    ./docs_generation.py generate           # Print docs to stdout
    ./docs_generation.py generate -o cli.md # Write to file
    ./docs_generation.py deploy --help      # See the documented tool
"""

import sys
from pathlib import Path
from typing import Any

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.app.builder import AppBuilder
from appinfra.app.docs import DocsGenerator
from appinfra.app.tools import Tool, ToolConfig


class DeployTool(Tool):
    """
    Deploy application to target environment.

    Handles the full deployment lifecycle including validation,
    building, and rollout with configurable strategies.

    Example:
        myapp deploy --env prod --version v1.2.3
        myapp deploy --env staging --dry-run
    """

    def __init__(self, parent: Any = None) -> None:
        config = ToolConfig(
            name="deploy",
            aliases=["d"],
            help_text="Deploy application to an environment",
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
        parser.add_argument(
            "--env",
            "-e",
            required=True,
            choices=["dev", "staging", "prod"],
            help="Target environment",
        )
        parser.add_argument(
            "--version",
            "-v",
            default="latest",
            help="Version to deploy (default: latest)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deployed without making changes",
        )
        parser.add_argument(
            "--strategy",
            choices=["rolling", "blue-green", "canary"],
            default="rolling",
            help="Deployment strategy (default: rolling)",
        )

    def run(self, **kwargs: Any) -> int:
        env = self.args.env
        version = self.args.version
        print(f"Deploying {version} to {env}")
        return 0


class StatusTool(Tool):
    """
    Check deployment status across environments.

    Example:
        myapp status
        myapp status --env prod
    """

    def __init__(self, parent: Any = None) -> None:
        config = ToolConfig(
            name="status",
            aliases=["s", "st"],
            help_text="Check deployment status",
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
        parser.add_argument(
            "--env",
            "-e",
            choices=["dev", "staging", "prod"],
            help="Filter by environment (default: all)",
        )
        parser.add_argument(
            "--format",
            choices=["table", "json", "yaml"],
            default="table",
            help="Output format (default: table)",
        )

    def run(self, **kwargs: Any) -> int:
        print("Checking status...")
        return 0


class RollbackTool(Tool):
    """
    Rollback to a previous deployment version.

    Example:
        myapp rollback --env prod
        myapp rollback --env prod --to v1.2.2
    """

    def __init__(self, parent: Any = None) -> None:
        config = ToolConfig(
            name="rollback",
            aliases=["rb"],
            help_text="Rollback to previous version",
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
        parser.add_argument(
            "--env",
            "-e",
            required=True,
            choices=["dev", "staging", "prod"],
            help="Target environment",
        )
        parser.add_argument(
            "--to",
            dest="target_version",
            help="Specific version to rollback to (default: previous)",
        )
        parser.add_argument(
            "--force",
            "-f",
            action="store_true",
            help="Skip confirmation prompts",
        )

    def run(self, **kwargs: Any) -> int:
        print(f"Rolling back {self.args.env}")
        return 0


class GenerateTool(Tool):
    """
    Generate CLI documentation.

    Creates markdown documentation from tool definitions.
    The generated docs include command descriptions, arguments,
    examples, and aliases - all extracted from the actual code.

    Example:
        myapp generate
        myapp generate -o docs/cli-reference.md
        myapp generate --title "MyApp Commands"
    """

    def __init__(self, parent: Any = None) -> None:
        config = ToolConfig(
            name="generate",
            aliases=["gen", "g"],
            help_text="Generate CLI documentation",
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
        parser.add_argument(
            "-o",
            "--output",
            type=Path,
            help="Output file path (default: stdout)",
        )
        parser.add_argument(
            "--title",
            default="CLI Reference",
            help="Documentation title",
        )
        parser.add_argument(
            "--no-examples",
            action="store_true",
            help="Exclude examples from output",
        )
        parser.add_argument(
            "--no-aliases",
            action="store_true",
            help="Exclude aliases from output",
        )

    def run(self, **kwargs: Any) -> int:
        generator = DocsGenerator(
            title=self.args.title,
            include_examples=not self.args.no_examples,
            include_aliases=not self.args.no_aliases,
        )

        markdown = generator.generate_all(self.app)

        if self.args.output:
            generator.generate_to_file(self.app, self.args.output)
            print(f"Documentation written to {self.args.output}")
        else:
            print(markdown)

        return 0


def main() -> int:
    """Build and run the example app."""
    app = (
        AppBuilder("myapp")
        .with_description("Example application demonstrating docs generation")
        .logging.with_level("warning")
        .done()
        .tools.with_tool(DeployTool())
        .with_tool(StatusTool())
        .with_tool(RollbackTool())
        .with_tool(GenerateTool())
        .done()
        .build()
    )
    return app.main()


if __name__ == "__main__":
    raise SystemExit(main())
