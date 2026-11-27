#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-run:
# ci-run: --subprocess
# ci-stop: 4
# ci-requires: port:25442
# ci-requires: port:25443

"""
FastAPI Server Framework Examples.

This example demonstrates two modes of the FastAPI server framework:
1. Direct mode - Simple server running in current process (blocking)
2. Subprocess mode - Server in separate process with queue-based IPC

Usage:
    # Direct mode (default)
    python fastapi_server.py

    # Subprocess mode with IPC demo
    python fastapi_server.py --subprocess
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from appinfra.app.fastapi import ServerBuilder
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


def create_simple_server(port: int = 25442) -> Server:
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


def create_subprocess_server(port: int = 25443) -> Server:
    """
    Create a server running in subprocess mode with IPC.

    Subprocess mode runs uvicorn in a separate process, communicating
    via multiprocessing queues the builder makes (server.request_queue,
    server.response_queue). This isolates the HTTP server from the
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
        .subprocess.with_ipc()
        .with_auto_restart(True)
        .with_max_restarts(3)
        .done()
        .routes.with_route("/health", health_handler)
        .done()
        .build()
    )


def run_subprocess_demo() -> int:
    """
    Demo subprocess mode with IPC communication.

    Shows the typical pattern:
    1. Build server with subprocess config (it makes the IPC queues)
    2. Start server (non-blocking)
    3. Main process handles queue messages (server.request_queue)
    """
    print("Starting subprocess mode demo...")

    server = create_subprocess_server()
    server.start_subprocess()

    print(f"Server started in subprocess (pid={server.pid})")
    print(f"Listening on http://localhost:{server.port}")
    print("Press Ctrl+C to stop")

    try:
        # Main process would typically process requests here
        # For demo, we just wait
        while server.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()

    return 0


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


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
        "--port", type=int, default=25442, help="Port for direct mode (default: 25442)"
    )
    args = parser.parse_args()

    if args.subprocess:
        return run_subprocess_demo()
    return run_direct_mode(args.port)


if __name__ == "__main__":
    sys.exit(main())
