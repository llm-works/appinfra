"""
Code quality checking commands.

Parent command for various code quality checks including function size analysis,
complexity checking, import analysis, etc.
"""

from typing import Any

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable


class CodeQualityTool(Tool):
    """
    Parent tool for code quality checks.

    This is a pure grouping command that requires a subcommand.
    Available subcommands:
    - check-funcs (cf): Check function sizes against guidelines
    - check-spdx (spdx): Check SPDX license headers on tracked .py files
    """

    def __init__(self, parent: Traceable | None = None):
        """
        Initialize the code-quality parent tool.

        Args:
            parent: Optional parent tool or application
        """
        config = ToolConfig(
            name="code-quality",
            aliases=["cq"],
            help_text="Code quality checking commands",
            description=(
                "Parent command for various code quality checks. "
                "Use subcommands to run specific checks. "
                "Example: infra code-quality check-funcs"
            ),
        )
        super().__init__(parent, config)

        # Import here to avoid circular dependency
        from .check_functions import CheckFunctionsTool
        from .check_spdx import CheckSpdxTool

        # Add subtools (no default - requires explicit subcommand)
        self.add_tool(CheckFunctionsTool(self), default=None)
        self.add_tool(CheckSpdxTool(self), default=None)

    def run(self, **kwargs: Any) -> int:
        """
        Run the selected subcommand or show help if none specified.

        If no subcommand is provided, displays the help screen.

        Returns:
            Exit code from subcommand (or 0 if help is shown)
        """
        # Check if a subcommand was provided
        cmd_var = self.group._cmd_var
        cmd = getattr(self.args, cmd_var, None)

        # If no subcommand, show help
        if cmd is None:
            if self.arg_prs:
                self.arg_prs.print_help()
            return 0

        return self.group.run(**kwargs)
