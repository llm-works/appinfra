#!/usr/bin/env python3
"""
FastAPI Server Framework Examples.

This example demonstrates three modes of the FastAPI server framework:
1. Direct mode - Simple server running in current process (blocking)
2. Subprocess mode - Server in separate process with queue-based IPC
3. AppBuilder integration - ServerPlugin for CLI applications

Usage:
    # Direct mode (default)
    python fastapi_server.py

    # Subprocess mode with IPC demo
    python fastapi_server.py --subprocess

    # AppBuilder integration
    python fastapi_server.py --cli serve
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import pathlib
import sys
import time
from dataclasses import dataclass
from typing import Any

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.append(project_root) if project_root not in sys.path else None

from appinfra.app.builder.app import AppBuilder
from appinfra.app.fastapi import ServerBuilder, ServerPlugin
from appinfra.app.fastapi.runtime.server import Server
from appinfra.log import Logger

# -----------------------------------------------------------------------------
# Route handlers
# -----------------------------------------------------------------------------


def health_handler() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok"}


def echo_handler(message: str = "hello") -> dict[str, str]:
    """Echo endpoint for testing."""
    return {"message": message, "timestamp": str(time.time())}


# -----------------------------------------------------------------------------
# Direct Mode Example
# -----------------------------------------------------------------------------


def create_simple_server(port: int = 8000) -> Server:
    """
    Create a simple server running in direct mode.

    Direct mode runs uvicorn in the current process (blocking).
    Suitable for simple deployments or development.
    """
    lg = Logger("simple-api")
    return (
        ServerBuilder(lg, "simple-api")
        .with_port(port)
        .with_title("Simple API")
        .with_description("Direct mode example")
        .routes.with_route("/health", health_handler)
        .with_route("/echo", echo_handler)
        .done()
        .build()
    )


# -----------------------------------------------------------------------------
# Subprocess Mode Example
# -----------------------------------------------------------------------------


@dataclass
class WorkRequest:
    """Request message for IPC."""

    id: str
    data: str


@dataclass
class WorkResponse:
    """Response message for IPC."""

    id: str
    result: str
    error: str | None = None


def create_subprocess_server(
    request_q: mp.Queue[Any],
    response_q: mp.Queue[Any],
    port: int = 8001,
) -> Server:
    """
    Create a server running in subprocess mode with IPC.

    Subprocess mode runs uvicorn in a separate process, communicating
    via multiprocessing queues. This isolates the HTTP server from the
    main application logic.

    Features:
    - Non-blocking start (returns immediately)
    - Auto-restart on crash
    - Queue-based request/response pattern
    - Subprocess log isolation
    """
    lg = Logger("worker-api")
    return (
        ServerBuilder(lg, "worker-api")
        .with_port(port)
        .with_title("Worker API")
        .subprocess.with_ipc(request_q, response_q)
        .with_auto_restart(enabled=True, max_restarts=3)
        .done()
        .routes.with_route("/health", health_handler)
        .done()
        .build()
    )


def run_subprocess_demo() -> int:
    """
    Demo subprocess mode with IPC communication.

    Shows the typical pattern:
    1. Create queues for IPC
    2. Build server with subprocess config
    3. Start server (non-blocking)
    4. Main process handles queue messages
    """
    print("Starting subprocess mode demo...")

    # Create IPC queues
    request_q: mp.Queue[Any] = mp.Queue()
    response_q: mp.Queue[Any] = mp.Queue()

    # Create and start server
    server = create_subprocess_server(request_q, response_q)
    proc = server.start_subprocess()

    print(f"Server started in subprocess (pid={proc.pid})")
    print(f"Listening on http://localhost:{server.config.port}")
    print("Press Ctrl+C to stop")

    try:
        # Main process would typically process requests here
        # For demo, we just wait
        while proc.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()

    return 0


# -----------------------------------------------------------------------------
# AppBuilder Integration Example
# -----------------------------------------------------------------------------


def create_cli_app() -> Any:
    """
    Create a CLI application with integrated HTTP server.

    ServerPlugin adds a "serve" command to the CLI that starts
    the HTTP server.

    Usage: python fastapi_server.py --cli serve
    """
    lg = Logger("cli-api")
    server = (
        ServerBuilder(lg, "cli-api")
        .with_port(8002)
        .with_title("CLI API")
        .routes.with_route("/health", health_handler)
        .done()
        .build()
    )

    return (
        AppBuilder("myapp")
        .with_description("CLI app with HTTP server")
        .logging.with_level("info")
        .done()
        .tools.with_plugin(ServerPlugin(server))
        .done()
        .build()
    )


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def run_cli_mode(cli_args: list[str]) -> int:
    """Run in AppBuilder CLI mode."""
    app = create_cli_app()
    sys.argv = ["myapp"] + cli_args
    result = app.main()
    return int(result) if result is not None else 0


def run_direct_mode(port: int) -> int:
    """Run server in direct mode (blocking)."""
    print(f"Starting server in direct mode on port {port}...")
    print("Press Ctrl+C to stop")

    server = create_simple_server(port=port)
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    return 0


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="FastAPI Server Examples")
    parser.add_argument(
        "--subprocess", action="store_true", help="Run subprocess mode demo"
    )
    parser.add_argument(
        "--cli", nargs="*", help="Run as CLI app (pass 'serve' to start server)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port for direct mode (default: 8000)"
    )
    args = parser.parse_args()

    if args.cli is not None:
        return run_cli_mode(args.cli if args.cli else [])
    if args.subprocess:
        return run_subprocess_demo()
    return run_direct_mode(args.port)


if __name__ == "__main__":
    sys.exit(main())
