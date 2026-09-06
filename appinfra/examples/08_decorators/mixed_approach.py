#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run: --help
# ci-run: server
# ci-run: analyze --file data.csv
# ci-run: export --output /tmp/appinfra-example-export.json
# ci-run: process --input data.csv --output /tmp/appinfra-example-out.csv --pipeline filter transform

"""
Mixed approach example.

Demonstrates mixing decorator-based tools with traditional class-based tools.
Use decorators for simple tools, classes for complex ones.

Pattern: Build app with AppBuilder (infrastructure + class-based tools),
then define simple tools via @app.tool() decorators on the built app.
"""

import sys
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.app import AppBuilder, Tool, ToolConfig
from appinfra.dot_dict import DotDict

# ============================================================================
# Complex tools use classes (when you need more control)
# ============================================================================


class ServerTool(Tool):
    """
    Complex server tool with extensive state management.

    Use classes when you need:
    - Complex initialization
    - State management
    - Multiple helper methods
    - Inheritance
    """

    def _create_config(self):
        return ToolConfig(
            name="server",
            help_text="Run HTTP server",
            description="Start the application HTTP server with full routing",
        )

    def add_args(self, parser):
        parser.add_argument("--port", type=int, help="Port to listen on")
        parser.add_argument("--workers", type=int, default=4, help="Number of workers")
        parser.add_argument(
            "--reload", action="store_true", help="Auto-reload on changes"
        )

    def setup(self, **kwargs):
        """Initialize server components."""
        # State first: super().setup() creates the logger and calls configure().
        self.routes = {}
        self.middleware = []
        super().setup(**kwargs)
        self.lg.info("Initializing server components...")
        self.load_routes()

    def configure(self):
        """Configure server after initialization."""
        self.lg.info("Configuring server...")

        # Port from args, else the app's YAML config, else a default.
        # self.config is this tool's ToolConfig; the YAML lives on self.app.
        app_config = self.app.config
        server_cfg = app_config.get("server", {}) if app_config else {}
        self.port = self.args.port or server_cfg.get("port", 8080)
        self.host = server_cfg.get("host", "127.0.0.1")

        # More complex configuration
        self.setup_middleware()

    def load_routes(self):
        """Load application routes."""
        self.routes["/health"] = self.handle_health
        self.routes["/api/status"] = self.handle_status
        self.lg.info(f"Loaded {len(self.routes)} routes")

    def setup_middleware(self):
        """Setup middleware pipeline."""
        # Add middleware
        self.middleware.append(self.log_request)
        self.lg.info(f"Configured {len(self.middleware)} middleware")

    def log_request(self, req):
        """Middleware to log requests."""
        self.lg.info(f"Request: {req}")

    def handle_health(self, req):
        """Health check endpoint."""
        return {"status": "ok"}

    def handle_status(self, req):
        """Status endpoint."""
        return {"uptime": 123, "requests": 456}

    def run(self, **kwargs):
        """Run the HTTP server."""
        self.lg.info(f"Starting server on {self.host}:{self.port}")
        self.lg.info(f"Workers: {self.args.workers}")

        if self.args.reload:
            self.lg.info("Auto-reload enabled")

        # Server run logic would go here
        # For example: appinfra.net.TCPServer(self.lg, self.port, handler).run()

        self.lg.info("Server running...")
        return 0


class ProcessorTool(Tool):
    """Data processor with complex pipeline."""

    def _create_config(self):
        return ToolConfig(name="process", help_text="Process data through pipeline")

    def add_args(self, parser):
        parser.add_argument("--input", required=True)
        parser.add_argument("--output", required=True)
        parser.add_argument("--pipeline", nargs="+", required=True)

    def setup(self, **kwargs):
        super().setup(**kwargs)  # creates the logger; must come first
        self.lg.info("Setting up processing pipeline...")
        self.processors = {}
        self.load_processors()

    def load_processors(self):
        """Load available processors."""
        self.processors["filter"] = self.filter_processor
        self.processors["transform"] = self.transform_processor
        self.processors["aggregate"] = self.aggregate_processor

    def filter_processor(self, data):
        """Filter processor."""
        return data  # Filter logic

    def transform_processor(self, data):
        """Transform processor."""
        return data  # Transform logic

    def aggregate_processor(self, data):
        """Aggregate processor."""
        return data  # Aggregate logic

    def run(self, **kwargs):
        """Run the processing pipeline."""
        self.lg.info(f"Processing {self.args.input} -> {self.args.output}")
        self.lg.info(f"Pipeline: {' -> '.join(self.args.pipeline)}")

        # Pipeline execution
        data = self.load_data(self.args.input)
        for step in self.args.pipeline:
            if step in self.processors:
                data = self.processors[step](data)
            else:
                self.lg.error(f"Unknown processor: {step}")
                return 1

        self.save_data(data, self.args.output)
        self.lg.info("Processing complete")
        return 0

    def load_data(self, path):
        """Load data from file."""
        return {}  # Load logic

    def save_data(self, data, path):
        """Save data to file."""
        pass  # Save logic


# ============================================================================
# Build app: AppBuilder for infrastructure + class tools, then decorators
# ============================================================================

app = (
    AppBuilder()
    .with_name("mixed-app")
    .with_version("1.0.0")
    .with_config(
        DotDict(
            logging=DotDict(level="info"), server=DotDict(host="0.0.0.0", port=8080)
        )
    )
    .tools.with_tool(ServerTool())
    .with_tool(ProcessorTool())
    .done()
    .build()
)


# Simple tools use decorators on the built app
@app.tool(name="analyze", help="Analyze data quickly")
@app.argument("--file", required=True)
@app.argument("--format", choices=["json", "csv"])
def analyze(self):
    """Quick data analysis tool."""
    self.lg.info(f"Analyzing {self.args.file} as {self.args.format}")
    # Simple analysis logic
    return 0


@app.tool(name="export", help="Export results")
@app.argument("--output", required=True)
@app.argument("--format", choices=["json", "csv", "xml"], default="json")
def export(self):
    """Export data to file."""
    self.lg.info(f"Exporting to {self.args.output} as {self.args.format}")
    # Simple export logic
    return 0


# Run
if __name__ == "__main__":
    sys.exit(app.main())
