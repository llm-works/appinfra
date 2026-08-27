# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Multiprocessing support for appinfra logging.

This module provides tools for logging across process boundaries:

- Queue mode: Subprocesses send log records to parent via queue
- Independent mode: Subprocesses configure their own logging from serialized config

Queue Mode Usage:
    # Parent process
    from multiprocessing import Process, Queue
    from .. import Logger
    from . import LogQueueListener, MPQueueHandler

    # Create queue and start listener
    log_queue = Queue()
    parent_logger = Logger(...)
    listener = LogQueueListener(log_queue, parent_logger)
    listener.start()

    # Spawn workers
    for i in range(4):
        Process(target=worker, args=(log_queue, f"worker-{i}")).start()

    # ... wait for workers ...
    listener.stop()


    # Subprocess
    def worker(log_queue, name):
        from . import MPQueueHandler
        import logging

        # Create logger with queue handler
        logger = logging.getLogger(name)
        logger.addHandler(MPQueueHandler(log_queue))
        logger.setLevel(logging.DEBUG)

        logger.info("Hello from subprocess")  # Sent to parent via queue

Independent Mode Usage:
    # Parent process
    from .. import LoggingBuilder
    config = builder.to_dict()  # LoggingBuilder instance
    Process(target=worker, args=(config, "worker-1"))

    # Subprocess
    def worker(log_config, name):
        logger = LoggingBuilder.from_dict(log_config, name=name).build()
        logger.info("Independent logging")
"""

from .queue_handler import MPQueueHandler
from .queue_listener import LogQueueListener

__all__ = [
    "MPQueueHandler",
    "LogQueueListener",
]
