#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Complete Deploy Tool Example

A realistic CLI tool that combines all UI features:
- Rich terminal output for status display
- Interactive prompts for confirmations
- Secret masking for credentials
- Progress bars for deployment steps

Run:
    python examples/09_ui/deploy_tool.py --help
    python examples/09_ui/deploy_tool.py deploy --env staging
    python examples/09_ui/deploy_tool.py status
    python examples/09_ui/deploy_tool.py rollback --env production
"""

import sys
import time
from pathlib import Path

# Add parent to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from appinfra.app import AppBuilder
from appinfra.app.tools import Tool, ToolConfig
from appinfra.security import SecretMasker
from appinfra.ui import (
    RICH_AVAILABLE,
    NonInteractiveError,
    Panel,
    Progress,
    Table,
    confirm,
    console,
    select,
)

# Simulated deployment data
ENVIRONMENTS = {
    "development": {"url": "dev.example.com", "replicas": 1},
    "staging": {"url": "staging.example.com", "replicas": 2},
    "production": {"url": "app.example.com", "replicas": 5},
}

DEPLOYMENT_STEPS = [
    "Validating configuration",
    "Building container image",
    "Pushing to registry",
    "Updating deployment manifest",
    "Rolling out new version",
    "Running health checks",
]


class DeployTool(Tool):
    """Deploy the application to an environment."""

    def __init__(self, parent=None):
        config = ToolConfig(
            name="deploy",
            aliases=["d"],
            help_text="Deploy the application to an environment",
        )
        super().__init__(parent, config)
        self.masker = SecretMasker()

    def add_args(self, parser):
        parser.add_argument(
            "--env",
            "-e",
            choices=list(ENVIRONMENTS.keys()),
            help="Target environment",
        )
        parser.add_argument(
            "--version",
            "-v",
            default="latest",
            help="Version to deploy (default: latest)",
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip confirmation prompts",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deployed without making changes",
        )

    def _get_env(self, env: str | None) -> str | None:
        """Get environment, prompting if needed."""
        if env:
            return env
        try:
            return select(
                "Select deployment environment:",
                choices=list(ENVIRONMENTS.keys()),
                default="staging",
            )
        except NonInteractiveError:
            console.print_error("Environment required. Use --env or run interactively.")
            return None

    def _show_plan(self, env: str, version: str, env_config: dict) -> None:
        """Display deployment plan panel."""
        console.print()
        panel = Panel(
            f"[bold]Environment:[/bold] {env}\n"
            f"[bold]Version:[/bold] {version}\n"
            f"[bold]URL:[/bold] {env_config['url']}\n"
            f"[bold]Replicas:[/bold] {env_config['replicas']}",
            title="Deployment Plan",
        )
        console.print(panel)
        console.print()

    def _confirm_production(self, auto_confirm: bool) -> bool:
        """Confirm production deployment. Returns True to proceed."""
        if auto_confirm:
            return True
        try:
            console.print_warning("You are about to deploy to PRODUCTION!")
            if not confirm("Are you sure you want to proceed?", default=False):
                console.print_info("Deployment cancelled")
                return False
            return True
        except NonInteractiveError:
            console.print_error(
                "Production deployments require confirmation. Use --yes to skip."
            )
            return False

    def _execute_deployment(self, env: str, version: str, env_config: dict) -> None:
        """Execute deployment with progress bar."""
        console.print()
        with Progress() as progress:
            task = progress.add_task(
                f"Deploying to {env}...", total=len(DEPLOYMENT_STEPS)
            )
            for _ in DEPLOYMENT_STEPS:
                time.sleep(0.5)
                progress.update(task, advance=1)

        console.print()
        console.print_success(f"Successfully deployed {version} to {env}!")
        console.print()
        console.print("[dim]Deployment log (credentials masked):[/dim]")
        log_msg = (
            f"Connected with api_key=sk-1234567890abcdefghij to {env_config['url']}"
        )
        console.print(f"  {self.masker.mask(log_msg)}")

    def run(self, **kwargs):
        env = self._get_env(self.args.env)
        if not env:
            return 1

        env_config = ENVIRONMENTS[env]
        self._show_plan(env, self.args.version, env_config)

        if self.args.dry_run:
            console.print_info("Dry run mode - no changes will be made")
            return 0

        if env == "production" and not self._confirm_production(self.args.yes):
            return 1

        self._execute_deployment(env, self.args.version, env_config)
        return 0


class StatusTool(Tool):
    """Show deployment status across all environments."""

    def __init__(self, parent=None):
        config = ToolConfig(
            name="status",
            aliases=["s"],
            help_text="Show deployment status",
        )
        super().__init__(parent, config)

    def _get_status_data(self) -> list[tuple[str, str, str, str, str]]:
        """Get simulated deployment status data."""
        return [
            (
                "development",
                "v2.3.1",
                "[green]Healthy[/green]",
                "1/1",
                "dev.example.com",
            ),
            (
                "staging",
                "v2.4.0-rc1",
                "[green]Healthy[/green]",
                "2/2",
                "staging.example.com",
            ),
            (
                "production",
                "v2.3.0",
                "[yellow]Degraded[/yellow]",
                "4/5",
                "app.example.com",
            ),
        ]

    def _build_status_table(
        self, statuses: list[tuple[str, str, str, str, str]]
    ) -> Table:
        """Build deployment status table."""
        table = Table(title="Deployment Status")
        table.add_column("Environment", style="cyan")
        table.add_column("Version", style="white")
        table.add_column("Status", style="green")
        table.add_column("Replicas")
        table.add_column("URL")
        for row in statuses:
            table.add_row(*row)
        return table

    def run(self, **kwargs):
        console.print()
        statuses = self._get_status_data()
        table = self._build_status_table(statuses)
        console.print(table)
        console.print()
        console.print_warning(
            "Production environment is degraded (4/5 replicas healthy)"
        )
        console.print()
        return 0


class RollbackTool(Tool):
    """Rollback to a previous deployment."""

    def __init__(self, parent=None):
        config = ToolConfig(
            name="rollback",
            aliases=["rb"],
            help_text="Rollback to a previous deployment",
        )
        super().__init__(parent, config)

    def add_args(self, parser):
        parser.add_argument(
            "--env",
            "-e",
            choices=list(ENVIRONMENTS.keys()),
            required=True,
            help="Target environment",
        )
        parser.add_argument(
            "--yes",
            "-y",
            action="store_true",
            help="Skip confirmation",
        )

    def _show_versions(self, env: str, versions: list[str]) -> None:
        """Display available versions."""
        console.print()
        console.print(f"[bold]Available versions for {env}:[/bold]")
        for i, v in enumerate(versions):
            marker = "[current]" if i == 0 else ""
            console.print(f"  {v} {marker}")
        console.print()

    def _select_target(self, versions: list[str]) -> str | None:
        """Select target version or return None on error."""
        try:
            return select("Select version to rollback to:", choices=versions[1:])
        except NonInteractiveError:
            console.print_error("Version selection required. Run interactively.")
            return None

    def run(self, **kwargs):
        env = self.args.env
        versions = ["v2.3.0", "v2.2.1", "v2.2.0", "v2.1.5"]
        self._show_versions(env, versions)

        target = self._select_target(versions)
        if target is None:
            return 1

        if not self.args.yes:
            try:
                if not confirm(f"Rollback {env} to {target}?", default=False):
                    console.print_info("Rollback cancelled")
                    return 0
            except NonInteractiveError:
                pass

        with console.status(f"Rolling back to {target}..."):
            time.sleep(1)
        console.print_success(f"Successfully rolled back {env} to {target}")
        return 0


def main():
    """Build and run the deploy tool."""
    app = (
        AppBuilder("deploy-tool")
        .with_description("Deployment management CLI with rich UI")
        .logging.with_level("warning")
        .done()
        .tools.with_tool(DeployTool())
        .with_tool(StatusTool())
        .with_tool(RollbackTool())
        .done()
        .build()
    )

    # Show rich availability
    if not RICH_AVAILABLE:
        print("Note: Install 'rich' for enhanced terminal output")
        print("  pip install rich")
        print()

    return app.main()


if __name__ == "__main__":
    sys.exit(main())
