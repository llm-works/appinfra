# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Testing utilities for appinfra.app tools and applications.

This module provides helper classes and utilities for testing tools
and applications in isolation without requiring full App instantiation.
"""

import argparse
from typing import Any
from unittest.mock import Mock

from .tracing.traceable import Traceable


class MockApp(Traceable):
    """
    Mock application parent for testing tools in isolation.

    Provides minimal interface needed by tools without requiring
    full App instantiation. Useful for unit testing tools that need
    access to parent resources like args, logger, and config.

    Attributes:
        args: Namespace containing command-line arguments
        lg: Logger instance (Mock by default)
        config: Configuration object (Mock by default)

    Example:
        >>> from appinfra.app.testing import MockApp
        >>> from appinfra.app.tools.base import Tool, ToolConfig
        >>>
        >>> class MyTool(Tool):
        ...     def run(self, **kwargs):
        ...         name = self.args.name
        ...         self.lg.info(f"Processing {name}")
        ...
        >>> # Create mock app with test arguments
        >>> mock_app = MockApp(args={'name': 'test', 'verbose': True})
        >>> tool = MyTool(parent=mock_app, config=ToolConfig(name='mytool'))
        >>> tool.setup()
        >>> tool.run()

    Example with custom logger:
        >>> import logging
        >>> logger = logging.getLogger('test')
        >>> mock_app = MockApp(
        ...     args={'file': 'data.txt'},
        ...     logger=logger
        ... )
        >>> tool = MyTool(parent=mock_app)
    """

    def __init__(
        self,
        args: dict[str, Any] | None = None,
        logger: Any | None = None,
        config: Any | None = None,
    ):
        """
        Initialize mock app.

        Args:
            args: Dictionary of arguments to expose as args namespace.
                  If None, creates empty Namespace.
            logger: Logger instance or Mock. If None, creates Mock logger.
            config: Configuration object or Mock. If None, creates Mock config.
        """
        super().__init__(parent=None)
        self.args = argparse.Namespace(**args) if args else argparse.Namespace()
        self.lg = logger or Mock()
        self.config = config or Mock()
