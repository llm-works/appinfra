#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# Minimal quick-start that mirrors the AppBuilder + @app.tool pattern shown
# in README.md. Runs against an installed wheel (no sys.path shim). Exercised
# by the smoke-wheel CI job to catch README-vs-installed API drift, broken
# top-level exports, missing wheel resources, and console-entry regressions.

import sys

from appinfra.app import AppBuilder

app = (
    AppBuilder("quickstart")
    .with_description("appinfra quick-start smoke")
    .with_standard_args(log=True, quiet=True)
    .build()
)


@app.tool(name="sync", help="Synchronize data")
@app.argument("--force", action="store_true", help="Force sync")
@app.argument("--limit", type=int, default=100)
def sync_tool(self):
    self.lg.info(f"Syncing {self.args.limit} items")
    if self.args.force:
        self.lg.warning("Force mode enabled")
    return 0


if __name__ == "__main__":
    sys.exit(app.main())
