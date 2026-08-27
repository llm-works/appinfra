# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Logging filter for secret masking.

Provides a logging.Filter implementation that masks secrets in
log messages before they are emitted.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .masking import SecretMasker


class SecretMaskingFilter(logging.Filter):
    """
    Logging filter that masks secrets in log messages.

    Applies secret masking to log record messages and arguments
    before the record is processed by handlers.

    Example:
        from . import SecretMaskingFilter, get_masker

        # Add to a logger
        logger = logging.getLogger("myapp")
        logger.addFilter(SecretMaskingFilter(get_masker()))

        # Secrets are now automatically masked
        logger.info("Connecting with password=super-secret-pass-123")
        # Output: "Connecting with password=[MASKED]"
    """

    def __init__(
        self,
        masker: SecretMasker | None = None,
        name: str = "",
    ):
        """
        Initialize the filter.

        Args:
            masker: SecretMasker instance (default: global masker)
            name: Filter name for logging hierarchy
        """
        super().__init__(name)
        self._masker = masker

    @property
    def masker(self) -> SecretMasker:
        """Get the masker instance."""
        if self._masker is None:
            from .masking import get_masker

            self._masker = get_masker()
        return self._masker

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter and mask secrets in the log record.

        Args:
            record: The log record to filter

        Returns:
            True (always allows the record through after masking)
        """
        # Mask the message
        if record.msg:
            record.msg = self.masker.mask(str(record.msg))

        # Mask arguments
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: self.masker.mask(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            else:
                record.args = tuple(
                    self.masker.mask(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )

        # Mask exception info if present
        if record.exc_text:
            record.exc_text = self.masker.mask(record.exc_text)

        return True


def add_masking_filter_to_logger(
    logger: logging.Logger | str,
    masker: SecretMasker | None = None,
) -> SecretMaskingFilter:
    """
    Add a secret masking filter to a logger.

    Convenience function for adding masking to existing loggers.

    Args:
        logger: Logger instance or logger name
        masker: SecretMasker instance (default: global masker)

    Returns:
        The created filter instance

    Example:
        from . import add_masking_filter_to_logger

        # By name
        add_masking_filter_to_logger("myapp")

        # By instance
        logger = logging.getLogger("myapp")
        add_masking_filter_to_logger(logger)
    """
    if isinstance(logger, str):
        logger = logging.getLogger(logger)

    filter_instance = SecretMaskingFilter(masker)
    logger.addFilter(filter_instance)
    return filter_instance
