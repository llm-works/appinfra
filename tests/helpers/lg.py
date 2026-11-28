# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""A real logger for tests whose runtime starts process tasks."""

from appinfra.log import LogConfig, Logger, LoggerFactory


def quiet_lg() -> Logger:
    """A real logger that emits warnings and above: a runtime carries its
    logger into each process task's child, which a mock cannot be."""
    return LoggerFactory.create_root(LogConfig.from_params(level="warning"))
