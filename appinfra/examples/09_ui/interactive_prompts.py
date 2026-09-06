#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Interactive Prompts Example

Demonstrates interactive CLI prompts using the appinfra.ui module:
- Confirmation prompts (yes/no)
- Text input with validation
- Password input (masked)
- Single selection from choices
- Multiple selection from choices

Run: python examples/09_ui/interactive_prompts.py

Note: Requires a TTY (interactive terminal). Will show fallback behavior
      when run in non-interactive mode (pipes, CI, etc.)
"""

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.ui import (
    NonInteractiveError,
    confirm,
    console,
    multiselect,
    password,
    select,
    text,
)


def demo_confirm():
    """Demonstrate confirmation prompts."""
    console.rule("Confirmation Prompts")

    try:
        # Basic confirmation
        if confirm("Do you want to continue?"):
            console.print_success("Continuing...")
        else:
            console.print_info("Cancelled")

        # With default=True
        if confirm("Enable verbose logging?", default=True):
            console.print_info("Verbose logging enabled")

        # Dangerous operation
        if confirm("Delete all temporary files?", default=False):
            console.print_warning("Deleting files...")
        else:
            console.print_info("Files preserved")

    except NonInteractiveError as e:
        console.print_warning(f"Non-interactive mode: {e}")

    console.print()


def demo_text_input():
    """Demonstrate text input prompts."""
    console.rule("Text Input")

    try:
        # Basic text input
        name = text("What is your project name?")
        console.print(f"Project: {name}")

        # With default value
        version = text("Version number:", default="1.0.0")
        console.print(f"Version: {version}")

        # With validation
        def validate_port(value):
            try:
                port = int(value)
                return 1 <= port <= 65535
            except ValueError:
                return False

        port = text(
            "Server port (1-65535):",
            default="8080",
            validate=validate_port,
        )
        console.print(f"Port: {port}")

    except NonInteractiveError as e:
        console.print_warning(f"Non-interactive mode: {e}")

    console.print()


def demo_password_input():
    """Demonstrate password input prompts."""
    console.rule("Password Input")

    try:
        # Basic password
        pwd = password("Enter database password:")
        console.print(f"Password length: {len(pwd)} characters")

        # With confirmation
        pwd = password("Create new password:", confirm=True)
        console.print_success("Password set successfully")

    except NonInteractiveError as e:
        console.print_warning(f"Non-interactive mode: {e}")

    console.print()


def demo_select():
    """Demonstrate single selection prompts."""
    console.rule("Single Selection")

    try:
        # Basic selection
        env = select(
            "Choose deployment environment:",
            choices=["development", "staging", "production"],
        )
        console.print(f"Selected environment: {env}")

        # With default
        region = select(
            "Choose region:",
            choices=["us-east-1", "us-west-2", "eu-west-1", "ap-northeast-1"],
            default="us-east-1",
        )
        console.print(f"Selected region: {region}")

    except NonInteractiveError as e:
        console.print_warning(f"Non-interactive mode: {e}")

    console.print()


def demo_multiselect():
    """Demonstrate multiple selection prompts."""
    console.rule("Multiple Selection")

    try:
        # Basic multiselect
        features = multiselect(
            "Select features to enable:",
            choices=["authentication", "caching", "logging", "metrics", "tracing"],
            default=["logging"],
        )
        console.print(f"Selected features: {', '.join(features)}")

        # Another example
        databases = multiselect(
            "Select databases to migrate:",
            choices=["users", "products", "orders", "analytics"],
        )
        if databases:
            console.print(f"Will migrate: {', '.join(databases)}")
        else:
            console.print_info("No databases selected")

    except NonInteractiveError as e:
        console.print_warning(f"Non-interactive mode: {e}")

    console.print()


def _show_project_summary(name: str, env: str, features: list[str]) -> None:
    """Display project configuration summary."""
    console.print()
    console.print("[bold]Project Configuration:[/bold]")
    console.print(f"  Name: {name}")
    console.print(f"  Environment: {env}")
    console.print(f"  Features: {', '.join(features) if features else 'none'}")
    console.print()


def demo_combined_workflow():
    """Demonstrate a complete workflow combining multiple prompts."""
    console.rule("Combined Workflow: New Project Setup")

    try:
        project_name = text("Project name:", default="my-app")
        env = select("Environment:", choices=["dev", "staging", "prod"])
        features = multiselect(
            "Features:",
            choices=["auth", "database", "cache", "logging"],
            default=["logging"],
        )
        _show_project_summary(project_name, env, features)

        if confirm("Create project with these settings?", default=True):
            console.print_success(f"Project '{project_name}' created!")
        else:
            console.print_info("Project creation cancelled")
    except NonInteractiveError as e:
        console.print_warning(f"Non-interactive mode: {e}")
    console.print()


def main():
    """Run all demos."""
    console.print()
    console.print("[bold blue]Interactive Prompts Demo[/bold blue]")
    console.print()
    console.print("[dim]Note: Some features require an interactive terminal.[/dim]")
    console.print(
        "[dim]Set APPINFRA_YES=1 to auto-confirm, or APPINFRA_NON_INTERACTIVE=1 to fail.[/dim]"
    )
    console.print()

    demo_confirm()
    demo_text_input()
    demo_password_input()
    demo_select()
    demo_multiselect()
    demo_combined_workflow()

    console.rule("Demo Complete")


if __name__ == "__main__":
    main()
