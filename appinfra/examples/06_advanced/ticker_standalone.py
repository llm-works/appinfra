#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

# ci-stop: 4

import sys
import time
from pathlib import Path

# Allow running from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

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
