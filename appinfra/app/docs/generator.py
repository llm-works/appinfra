# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Documentation generator for CLI tools.

Generates markdown documentation from tool definitions, including
arguments, help text, and examples extracted from docstrings.
"""

from __future__ import annotations

import argparse
import re
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core.app import App
    from ..tools.base import Tool


class DocsGenerator:
    """
    Generate documentation from tool definitions.

    Creates markdown documentation that stays in sync with code
    by extracting information from tool configurations and argument parsers.

    Example:
        from . import DocsGenerator

        generator = DocsGenerator()

        # Generate full CLI reference
        markdown = generator.generate_all(app)

        # Generate for a single tool
        tool_doc = generator.generate_tool_doc(tool)

        # Write to file
        generator.generate_to_file(app, Path("docs/cli.md"))
    """

    def __init__(
        self,
        *,
        title: str = "CLI Reference",
        include_examples: bool = True,
        include_aliases: bool = True,
    ):
        """
        Initialize the generator.

        Args:
            title: Title for the generated documentation
            include_examples: Include examples from docstrings
            include_aliases: Include command aliases
        """
        self.title = title
        self.include_examples = include_examples
        self.include_aliases = include_aliases

    def generate_all(self, app: App) -> str:
        """
        Generate full CLI reference documentation.

        Args:
            app: Application instance with registered tools

        Returns:
            Markdown documentation string
        """
        output = StringIO()

        # Title
        output.write(f"# {self.title}\n\n")

        # App description
        if hasattr(app, "description") and app.description:
            output.write(f"{app.description}\n\n")

        # Table of contents
        tools = self._get_tools(app)
        if tools:
            output.write("## Commands\n\n")
            for tool in tools:
                name = self._get_tool_name(tool)
                output.write(f"- [{name}](#{name.replace(' ', '-')})\n")
            output.write("\n---\n\n")

        # Tool documentation
        for tool in tools:
            doc = self.generate_tool_doc(tool, app_name=getattr(app, "name", "app"))
            output.write(doc)
            output.write("\n---\n\n")

        return output.getvalue()

    def _write_header(
        self, output: StringIO, tool: Tool, app_name: str, name: str, depth: int
    ) -> None:
        """Write command name, help, aliases, and description."""
        heading = "#" * (3 + depth)
        output.write(f"{heading} `{app_name} {name}`\n\n")
        if tool.config and tool.config.help_text:
            output.write(f"{tool.config.help_text}\n\n")
        if self.include_aliases and tool.config and tool.config.aliases:
            output.write(
                f"**Aliases:** {', '.join(f'`{a}`' for a in tool.config.aliases)}\n\n"
            )
        description = self._get_description(tool)
        if description:
            output.write(f"{description}\n\n")

    def _write_examples(
        self, output: StringIO, tool: Tool, app_name: str, name: str
    ) -> None:
        """Write examples section if enabled."""
        if not self.include_examples:
            return
        examples = self._extract_examples(tool, app_name, name)
        if examples:
            output.write(f"**Examples:**\n\n```bash\n{examples}\n```\n\n")

    def _write_subcommands(
        self, output: StringIO, tool: Tool, app_name: str, name: str, depth: int
    ) -> None:
        """Write subcommands section if present."""
        if not (hasattr(tool, "_group") and tool._group):
            return
        subtools = list(tool._group._tools.values())
        if subtools:
            output.write("**Subcommands:**\n\n")
            for subtool in subtools:
                output.write(
                    self.generate_tool_doc(
                        subtool, app_name=f"{app_name} {name}", depth=depth + 1
                    )
                )

    def generate_tool_doc(
        self, tool: Tool, *, app_name: str = "app", depth: int = 0
    ) -> str:
        """Generate documentation for a single tool."""
        output = StringIO()
        name = self._get_tool_name(tool)
        self._write_header(output, tool, app_name, name, depth)
        args_doc = self._generate_arguments_doc(tool)
        if args_doc:
            output.write(args_doc)
        self._write_examples(output, tool, app_name, name)
        self._write_subcommands(output, tool, app_name, name, depth)
        return output.getvalue()

    def generate_to_file(self, app: App, output_path: Path) -> None:
        """
        Generate documentation and write to file.

        Args:
            app: Application instance
            output_path: Path to write markdown file
        """
        markdown = self.generate_all(app)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown)

    def _get_tools(self, app: App) -> list[Tool]:
        """Get all registered tools from an app."""
        tools = []

        # Try different ways to access tools
        if hasattr(app, "registry") and app.registry:
            # AppBuilder-created apps use registry
            for name in app.registry.list_tools():
                tool = app.registry.get_tool(name)
                if tool:
                    tools.append(tool)
        elif hasattr(app, "_tools") and app._tools:
            tools.extend(app._tools.values())
        elif hasattr(app, "tool_registry"):
            tools.extend(app.tool_registry.get_all())

        return tools

    def _get_tool_name(self, tool: Tool) -> str:
        """Get the tool name."""
        if tool.config and tool.config.name:
            return tool.config.name
        return getattr(tool, "name", "unknown")

    def _get_description(self, tool: Tool) -> str:
        """Get tool description from config or docstring."""
        # Try config description
        if tool.config and tool.config.description:
            return tool.config.description

        # Try class docstring
        if tool.__class__.__doc__:
            doc = tool.__class__.__doc__.strip()
            # Return first paragraph
            paragraphs = doc.split("\n\n")
            if paragraphs:
                return paragraphs[0].replace("\n", " ").strip()

        return ""

    def _get_parser(self, tool: Tool) -> argparse.ArgumentParser | None:
        """Get or create argument parser for tool."""
        parser = getattr(tool, "_arg_prs", None) or getattr(tool, "arg_prs", None)
        if isinstance(parser, argparse.ArgumentParser):
            return parser
        parser = argparse.ArgumentParser()
        if hasattr(tool, "add_args"):
            try:
                tool.add_args(parser)
                return parser
            except Exception:
                return None
        return None

    def _generate_arguments_doc(self, tool: Tool) -> str:
        """Generate arguments documentation table."""
        parser = self._get_parser(tool)
        if not parser:
            return ""
        args = self._extract_arguments(parser)
        if not args:
            return ""
        output = StringIO()
        output.write(
            "**Arguments:**\n\n| Name | Type | Required | Default | Description |\n"
        )
        output.write("|------|------|----------|---------|-------------|\n")
        for arg in args:
            req = "yes" if arg["required"] else "no"
            output.write(
                f"| `{arg['name']}` | {arg['type']} | {req} | {arg['default']} | {arg['help']} |\n"
            )
        output.write("\n")
        return output.getvalue()

    def _get_arg_name(self, action: Any) -> str:
        """Get the best name for an argument."""
        if action.option_strings:
            name: str = action.option_strings[0]
            for opt in action.option_strings:
                if opt.startswith("--"):
                    return str(opt)
            return str(name)
        return str(action.dest)

    def _get_arg_type(self, action: Any) -> str:
        """Determine the type string for an argument."""
        if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
            return "flag"
        if isinstance(action, argparse._CountAction):
            return "count"
        if action.type:
            return getattr(action.type, "__name__", str(action.type))
        if action.choices:
            return "choice"
        return "string"

    def _get_arg_default(self, action: Any) -> str:
        """Get the default value string for an argument."""
        if action.default is None or action.default == argparse.SUPPRESS:
            return "-"
        if isinstance(action.default, bool):
            return str(action.default).lower()
        return str(action.default)

    def _extract_arguments(
        self, parser: argparse.ArgumentParser
    ) -> list[dict[str, Any]]:
        """Extract argument information from parser."""
        args = []

        for action in parser._actions:
            if isinstance(action, argparse._HelpAction):
                continue

            required = action.required if hasattr(action, "required") else False
            if not action.option_strings:
                required = action.nargs not in ("?", "*")

            args.append(
                {
                    "name": self._get_arg_name(action),
                    "type": self._get_arg_type(action),
                    "required": required,
                    "default": self._get_arg_default(action),
                    "help": action.help or "",
                    "choices": action.choices,
                }
            )

        return args

    def _get_tool_docstring(self, tool: Tool) -> str:
        """Get combined docstring from tool class and run method."""
        doc = tool.__class__.__doc__ or ""
        if hasattr(tool, "run") and tool.run.__doc__:
            doc += "\n" + tool.run.__doc__
        return doc

    def _clean_example_block(self, block: str) -> list[str]:
        """Clean indentation from example block."""
        lines = block.split("\n")
        min_indent = min(
            (len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()), default=0
        )
        return [line[min_indent:] for line in lines if line.strip()]

    def _extract_examples(self, tool: Tool, app_name: str, tool_name: str) -> str:
        """Extract examples from tool docstring."""
        doc = self._get_tool_docstring(tool)
        if not doc:
            return f"{app_name} {tool_name}"
        examples = []
        pattern = re.compile(
            r"(?:Example|Examples|Usage):\s*\n((?:\s+.+\n?)+)",
            re.IGNORECASE | re.MULTILINE,
        )
        for match in pattern.finditer(doc):
            examples.extend(self._clean_example_block(match.group(1)))
        return "\n".join(examples) if examples else f"{app_name} {tool_name}"
