#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Simple decorator example.

Demonstrates the basic decorator API for creating simple CLI tools.
This is the recommended approach for straightforward tools.
"""

import pathlib
import sys

# Add project root to path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.insert(0, project_root) if project_root not in sys.path else None

from appinfra.app import App
from appinfra.dot_dict import DotDict

# Create app with simple config
app = App(config=DotDict(logging=DotDict(level="info")))

# Define tools using decorators
# Note: Decorators apply in order, so we use functional style for clarity
greet = app.tool(name="greet", help="Greet someone")(
    lambda self: (
        self.lg.info(f"Hello {self.args.name}{'!' if self.args.enthusiastic else '.'}"),
        0,
    )[1]
)
greet = app.argument("--name", default="World", help="Name to greet")(greet)
greet = app.argument("--enthusiastic", action="store_true", help="Add excitement")(
    greet
)


def analyze_func(self):
    """Analyze a data file."""
    if self.args.verbose:
        self.lg.info(f"Analyzing file: {self.args.file}")
        self.lg.info(f"Format: {self.args.format}")

    # Analysis logic here
    self.lg.info(f"File {self.args.file} analyzed successfully")
    return 0


# Apply decorators in correct order
analyze = app.tool(name="analyze", help="Analyze a file")(analyze_func)
analyze = app.argument("--file", required=True, help="File to analyze")(analyze)
analyze = app.argument("--format", choices=["json", "csv", "xml"], default="json")(
    analyze
)
analyze = app.argument("--verbose", action="store_true", help="Verbose output")(analyze)


# NEW: Natural decorator syntax (Python 3.9+)
# You can now use @ notation in natural reading order!
@app.tool(name="process", help="Process data")
@app.argument("--input", required=True, help="Input file")
@app.argument("--output", required=True, help="Output file")
@app.argument("--workers", type=int, default=4, help="Number of workers")
def process(self):
    """Process data with multiple workers."""
    self.lg.info(f"Processing {self.args.input} -> {self.args.output}")
    self.lg.info(f"Using {self.args.workers} workers")
    return 0


if __name__ == "__main__":
    sys.exit(app.main())
