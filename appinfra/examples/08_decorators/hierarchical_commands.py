#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Hierarchical commands example.

Demonstrates creating parent tools with subcommands using the decorator API.
Shows the pattern: app.py db migrate, app.py db status, etc.
"""

import pathlib
import sys

# Add project root to path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.insert(0, project_root) if project_root not in sys.path else None

from appinfra.app import App
from appinfra.dot_dict import DotDict

# Create app
app = App(
    config=DotDict(
        logging=DotDict(level="info"),
        database=DotDict(host="localhost", port=5432, name="mydb"),
    )
)


# Database command group
@app.tool(name="db", help="Database operations")
def db_tool(self):
    """Database management commands."""
    pass


@db_tool.subtool(name="migrate", help="Run database migrations")
@app.argument("--target", help="Target migration version")
@app.argument("--dry-run", action="store_true", help="Show what would be done")
def db_migrate(self):
    """Run database migrations."""
    target = self.args.target or "latest"

    if self.args.dry_run:
        self.lg.info(f"Would migrate database to {target}")
    else:
        self.lg.info(f"Migrating database to {target}...")
        # Migration logic here
        self.lg.info("Migration complete")

    return 0


@db_tool.subtool(name="status", help="Check database status")
def db_status(self):
    """Check database connection and status."""
    self.lg.info("Checking database connection...")
    # Status check logic here
    self.lg.info("Database is healthy")
    return 0


@db_tool.subtool(name="backup", help="Backup database")
@app.argument("--output", required=True, help="Backup file path")
@app.argument("--compress", action="store_true", help="Compress backup")
def db_backup(self):
    """Backup the database."""
    self.lg.info(f"Backing up database to {self.args.output}")

    if self.args.compress:
        self.lg.info("Using compression")

    # Backup logic here
    self.lg.info("Backup complete")
    return 0


# Another command group - cache operations
@app.tool(name="cache", help="Cache operations")
def cache_tool(self):
    """Cache management commands."""
    pass


@cache_tool.subtool(name="clear", help="Clear cache")
@app.argument("--pattern", help="Pattern to match keys")
def cache_clear(self):
    """Clear cache entries."""
    pattern = self.args.pattern or "*"
    self.lg.info(f"Clearing cache entries matching: {pattern}")
    # Clear logic here
    self.lg.info("Cache cleared")
    return 0


@cache_tool.subtool(name="stats", help="Show cache statistics")
def cache_stats(self):
    """Show cache statistics."""
    self.lg.info("Cache statistics:")
    self.lg.info("  Entries: 1234")
    self.lg.info("  Hit rate: 85%")
    self.lg.info("  Size: 128 MB")
    return 0


if __name__ == "__main__":
    sys.exit(app.main())
