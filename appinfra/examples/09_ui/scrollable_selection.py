#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Scrollable Selection Example

Demonstrates the scrollable selection features using InquirerPy.
These provide arrow-key navigation with configurable page height.

Requirements:
    pip install appinfra[ui]

Usage:
    python scrollable_selection.py
"""

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.ui import (
    INQUIRER_AVAILABLE,
    NonInteractiveError,
    select_scrollable,
    select_table,
)

# Sample process data for table demo
SAMPLE_PROCESSES = [
    {
        "pid": "1234",
        "name": "nginx",
        "cpu": "2.3%",
        "mem": "128MB",
        "status": "running",
    },
    {
        "pid": "1235",
        "name": "postgres",
        "cpu": "15.7%",
        "mem": "2.1GB",
        "status": "running",
    },
    {
        "pid": "1236",
        "name": "redis",
        "cpu": "1.2%",
        "mem": "512MB",
        "status": "running",
    },
    {
        "pid": "1237",
        "name": "celery",
        "cpu": "8.4%",
        "mem": "256MB",
        "status": "running",
    },
    {
        "pid": "1238",
        "name": "gunicorn",
        "cpu": "5.1%",
        "mem": "384MB",
        "status": "running",
    },
    {"pid": "1239", "name": "node", "cpu": "3.2%", "mem": "192MB", "status": "running"},
    {
        "pid": "1240",
        "name": "python",
        "cpu": "0.5%",
        "mem": "64MB",
        "status": "sleeping",
    },
    {"pid": "1241", "name": "cron", "cpu": "0.0%", "mem": "8MB", "status": "sleeping"},
    {"pid": "1242", "name": "sshd", "cpu": "0.1%", "mem": "16MB", "status": "running"},
    {
        "pid": "1243",
        "name": "docker",
        "cpu": "4.8%",
        "mem": "1.2GB",
        "status": "running",
    },
]


def demo_scrollable_list() -> None:
    """Demo basic scrollable list selection."""
    print("\n=== Scrollable List Demo ===\n")

    servers = [f"server-{i:03d}" for i in range(50)]
    idx = select_scrollable("Select a server to connect:", servers, max_height=10)

    if idx is not None:
        print(f"\nYou selected: {servers[idx]}")
    else:
        print("\nCancelled")


def demo_table_selection() -> None:
    """Demo table-style selection with columns."""
    print("\n=== Table Selection Demo ===\n")

    selected = select_table(
        "Select a process to inspect:",
        SAMPLE_PROCESSES,
        columns=["pid", "name", "cpu", "mem", "status"],
        max_height=5,
    )

    if selected:
        print(f"\nSelected: {selected['name']} (PID {selected['pid']})")
    else:
        print("\nCancelled")


def demo_custom_styling() -> None:
    """Demo custom styling options."""
    print("\n=== Custom Styling Demo ===\n")

    environments = ["development", "staging", "production", "dr-site"]
    idx = select_scrollable(
        "Select deployment target:",
        environments,
        max_height=10,
        highlight_color="#00aa00",
        highlight_text="#ffffff",
    )

    if idx is not None:
        print(f"\nDeploying to: {environments[idx]}")
    else:
        print("\nDeployment cancelled")


def main() -> None:
    """Run all demos."""
    print("Scrollable Selection Examples")
    print("=" * 40)

    if not INQUIRER_AVAILABLE:
        print("\nWarning: InquirerPy not installed.")
        print("Install with: pip install appinfra[ui]")
        print("Falling back to basic numbered selection.\n")

    try:
        for demo in (demo_scrollable_list, demo_table_selection, demo_custom_styling):
            try:
                demo()
            except NonInteractiveError as e:
                # No terminal (piped, CI): report and move on, like the other
                # prompt examples.
                print(f"Non-interactive mode: {e}")
    except KeyboardInterrupt:
        print("\n\nExited")


if __name__ == "__main__":
    main()
