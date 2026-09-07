# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Etc path discovery tool."""

import sys
from importlib.resources import files
from typing import Any

from ...app.tools import Tool, ToolConfig
from ...app.tracing.traceable import Traceable


class EtcPathTool(Tool):
    """Print the path to the etc directory."""

    def __init__(self, parent: Traceable | None = None):
        """Initialize the etc-path tool.

        Args:
            parent: Optional parent tool or application.
        """
        config = ToolConfig(
            name="etc-path",
            help_text="Print path to etc directory",
            description="Outputs the filesystem path to the etc directory for configuration files",
        )
        super().__init__(parent, config)

    def add_args(self, parser: Any) -> None:
        """Add command-line arguments."""
        parser.add_argument(
            "--local",
            action="store_true",
            help="Print the etc directory in effect for this run instead of the packaged one",
        )

    def run(self, local: bool = False, **kwargs: Any) -> int:
        """Print the etc directory path.

        Args:
            local: If True, print the directory of the config file this run
                resolved to (``app.etc_dir``) instead of the packaged etc.

        Returns:
            Exit code (0 for success, 1 for error).
        """
        # Check both direct arg and parsed args (framework passes args via self.args)
        try:
            use_local = local or getattr(self.args, "local", False)
        except Exception:
            use_local = local
        if use_local:
            etc_dir = self.app.etc_dir
            if etc_dir is None:
                print("Error: no etc directory resolved for this run", file=sys.stderr)
                return 1
            print(etc_dir)
        else:
            print(files("appinfra") / "etc")
        return 0
