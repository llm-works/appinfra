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
2. Subprocess mode - Server in separate process with Chan-based IPC

Usage:
    # Direct mode (default)
    python fastapi_server.py

    # Subprocess mode with IPC demo
    python fastapi_server.py --subprocess
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from fastapi import Request

from appinfra.app.fastapi import ServerBuilder
from appinfra.app.fastapi.runtime.server import Server
from appinfra.log import Logger
from appinfra.runtime import ChanClosedError

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

    data: str


@dataclass
class WorkResponse:
    """Response message for IPC."""

    result: str


async def work_handler(data: str, request: Request) -> dict[str, str]:
    """Hands the work to the main process and returns its answer."""
    ipc = request.app.state.ipc_channel
    response: WorkResponse = await ipc.submit(WorkRequest(data), timeout=10.0)
    return {"result": response.result}


def create_subprocess_server(port: int = 25443) -> Server:
    """
    Create a server running in subprocess mode with IPC.

    Subprocess mode runs uvicorn in a separate process. Its routes send
    requests to the main process on server.requests, a Chan homed there,
    each with a Chan to reply on. This isolates the HTTP server from the
    main application logic.

    Features:
    - Non-blocking start (returns immediately)
    - Auto-restart on crash; a restarted server sends to the same Chan
    - Request/reply over Chans: no ids, no polling
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
        .with_route("/work/{data}", work_handler)
        .done()
        .build()
    )


def serve_requests(server: Server) -> None:
    """Answer the server's requests, each on the Chan it came with, until
    the requests Chan is closed. A restarted server sends to the same Chan,
    so this goes on across a crash."""
    assert server.requests is not None
    for request, reply in server.requests:
        try:
            reply.send(WorkResponse(result=request.data.upper()), timeout=1.0)
        except ChanClosedError:
            pass  # the route stopped waiting for it


def run_subprocess_demo() -> int:
    """
    Demo subprocess mode with IPC communication.

    Shows the typical pattern:
    1. Build server with subprocess config (it makes server.requests)
    2. Answer its requests on a thread (try GET /work/hello)
    3. Run the server: start() blocks until it is stopped, or has ended
       with no restart left, and stops it on Ctrl+C
    """
    server = create_subprocess_server()
    assert server.requests is not None
    print("Starting subprocess mode demo...")
    print(f"Listening on http://localhost:{server.config.port}")
    print("Press Ctrl+C to stop")

    serving = threading.Thread(target=serve_requests, args=(server,))
    serving.start()
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.requests.close()  # ends serve_requests()
        serving.join()

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
