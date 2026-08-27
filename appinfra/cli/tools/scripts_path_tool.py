# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Scripts path discovery tool."""

from importlib.resources import files
from typing import Any

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable


class ScriptsPathTool(Tool):
    """Print the path to the installed scripts directory."""

    def __init__(self, parent: Traceable | None = None):
        """Initialize the scripts-path tool.

        Args:
            parent: Optional parent tool or application.
        """
        config = ToolConfig(
            name="scripts-path",
            help_text="Print path to installed scripts directory",
            description="Outputs the filesystem path to the scripts directory for Makefile integration",
        )
        super().__init__(parent, config)

    def run(self, **kwargs: Any) -> int:
        """Print the scripts directory path.

        Returns:
            Exit code (0 for success).
        """
        print(files("appinfra") / "scripts")
        return 0
