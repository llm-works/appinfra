#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

import pathlib
import sys
import time

# Add the project root to the path
project_root = str(pathlib.Path(__file__).resolve().parents[3])
sys.path.append(project_root) if project_root not in sys.path else None

import appinfra
from appinfra.log import LogConfig, LoggerFactory


class Ticker(appinfra.time.Ticker, appinfra.time.TickerHandler):
    def __init__(self):
        config = LogConfig.from_params(level="info", location=1, micros=True)
        lg = LoggerFactory.create_root(config)
        super().__init__(lg, self, secs=1)
        self._last_t = time.monotonic()

    def ticker_start(self):
        self._lg.info(
            "start",
            extra={"after": appinfra.time.since_str(self._last_t, precise=True)},
        )
        self._last_t = time.monotonic()

    def ticker_tick(self):
        self._lg.info(
            "tick", extra={"after": appinfra.time.since_str(self._last_t, precise=True)}
        )
        self._last_t = time.monotonic()


def main():
    Ticker().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
