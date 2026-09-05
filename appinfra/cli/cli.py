#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Infra CLI - Utility commands for the infra framework.

Usage:
    appinfra scaffold my-project --with-db
    appinfra scaffold my-api --with-db --with-server
    appinfra --help
"""

import sys
from pathlib import Path

# Add project root to path for running as script (before package is installed)
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import appinfra

# Use absolute imports since this module is designed to run as a script
from appinfra.app import App, AppBuilder
from appinfra.cli.tools.code_quality import CodeQualityTool
from appinfra.cli.tools.completion_tool import CompletionTool
from appinfra.cli.tools.config_tool import ConfigTool
from appinfra.cli.tools.docs_tool import DocsTool
from appinfra.cli.tools.doctor_tool import DoctorTool
from appinfra.cli.tools.etc_path_tool import EtcPathTool
from appinfra.cli.tools.pg_tool import PgTool
from appinfra.cli.tools.scaffold_tool import ScaffoldTool
from appinfra.cli.tools.scripts_path_tool import ScriptsPathTool
from appinfra.cli.tools.version_tool import VersionTool

_BASE_CONFIG = Path(appinfra.__file__).parent / "etc" / "infra.yaml"

# All CLI tools
_TOOLS = [
    CodeQualityTool,
    CompletionTool,
    ConfigTool,
    DoctorTool,
    DocsTool,
    PgTool,
    ScaffoldTool,
    ScriptsPathTool,
    EtcPathTool,
    VersionTool,
]


def _build_app() -> App:
    """Build the CLI application with all tools registered."""
    builder = (
        AppBuilder("appinfra")
        .with_description("Infra framework utility commands")
        .without_standard_args()
        .with_standard_args(
            help=True, log_level=True, quiet=True, etc_dir=True, config_file=True
        )
        .with_config_spec("llm-works", "appinfra", _BASE_CONFIG)
        .version.with_semver(appinfra.__version__)
        .with_build_info()
        .done()
        .advanced.with_argument(
            "-v",
            action="version",
            version=f"appinfra {appinfra.__version__}",
        )
        .done()
    )
    for tool_cls in _TOOLS:
        builder = builder.tools.with_tool(tool_cls()).done()
    return builder.logging.with_level("info").done().build()


def main() -> int:
    """Main entry point for infra CLI."""
    return _build_app().main()


if __name__ == "__main__":
    exit(main())
