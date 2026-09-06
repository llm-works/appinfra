#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-stop: 4

import json
import sys
import time
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import appinfra
from appinfra.log import LogConfig, LoggerFactory


class Syn(appinfra.time.TickerHandler, appinfra.net.HTTPRequestHandler):
    """Syncer that implements TickerHandler and HTTPRequestHandler."""

    def __init__(self, lg):
        self._lg = lg
        self._last_t = time.monotonic()
        self._lock = None
        self._msg = None
        self._ticker = None

    def start(self):
        """Start the ticker - required by TCPServer interface."""
        self._lg.info("starting syn ticker...")
        # Initialize local state for single-process mode
        if self._lock is None:
            import threading

            self._lock = threading.Lock()
            self._msg = {"last_t": time.monotonic()}

        # Create and start the ticker with this handler
        self._ticker = appinfra.time.Ticker(self._lg, self, secs=1)
        self._ticker.start()
        self._lg.info("syn ticker started")

    def ticker_start(self, manager=None):
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

    def ticker_tick(self):
        self._lg.info("tick", extra={"after": appinfra.time.since(self._last_t)})
        self._last_t = time.monotonic()
        with self._lock:
            self._msg.update({"last_t": self._last_t})

    def do_GET(self, instance):
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


def main():
    config = LogConfig.from_params("info")
    lg = LoggerFactory.create_root(config)

    # Create and run the server
    server = appinfra.net.TCPServer(lg, 9001, Syn(lg))
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
