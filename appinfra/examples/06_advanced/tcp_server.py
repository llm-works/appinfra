#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-stop: 4
# ci-requires: port:25444

import http.server
import json
import sys
import time
from pathlib import Path
from typing import Any

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import appinfra
from appinfra.log import LogConfig, Logger, LoggerFactory


class Syn(appinfra.time.TickerHandler):
    """Ticker handler whose state TCPServer serves over HTTP (it delegates do_GET here)."""

    def __init__(self, lg: Logger) -> None:
        self._lg = lg
        self._last_t = time.monotonic()
        # Set in ticker_start: manager proxies in multiprocessing mode
        self._lock: Any = None
        self._msg: Any = None

    def ticker_start(self, manager: Any = None) -> None:
        """Called when ticker starts in multiprocessing mode."""
        self._lg.info("start", extra={"after": appinfra.time.since(self._last_t)})
        self._last_t = time.monotonic()

        if manager:
            # Multiprocessing mode
            self._lock = manager.Lock()
            self._msg = manager.dict()
        else:
            # Single-process mode - use threading
            import threading

            if self._lock is None:
                self._lock = threading.Lock()
                self._msg = {"last_t": self._last_t}

    def ticker_tick(self) -> None:
        self._lg.info("tick", extra={"after": appinfra.time.since(self._last_t)})
        self._last_t = time.monotonic()
        with self._lock:
            self._msg.update({"last_t": self._last_t})

    def do_GET(self, instance: http.server.BaseHTTPRequestHandler) -> None:
        """Handle GET requests - return current shared state."""
        if self._lock is None or self._msg is None:
            instance.send_response(500)
            instance.send_header("Content-type", "application/json")
            instance.end_headers()
            instance.wfile.write(
                json.dumps({"error": "Server not initialized"}).encode()
            )
            return

        with self._lock:
            try:
                instance.send_response(200)
                instance.send_header("Content-type", "application/json")
                instance.end_headers()
                instance.wfile.write(json.dumps(self._msg.copy()).encode())
            except Exception as e:
                self._lg.error(f"error handling GET request: {e}")
                instance.send_response(500)
                instance.send_header("Content-type", "application/json")
                instance.end_headers()
                instance.wfile.write(
                    json.dumps({"error": "Internal server error"}).encode()
                )


def main() -> int:
    config = LogConfig.from_params("info")
    lg = LoggerFactory.create_root(config)

    # The ticker runs in its own process; the server serves the state it updates
    syn = Syn(lg)
    ticker = appinfra.time.Ticker(lg, syn, secs=1)
    server = appinfra.net.TCPServer(lg, 25444, syn, ticker=ticker)
    lg.info("starting tcp server...")

    try:
        result = server.run()
        lg.info(f"tcp server finished with result: {result}")
        return result
    except Exception as e:
        lg.error(f"tcp server error: {e}")
        import traceback

        lg.error(f"traceback: {traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
