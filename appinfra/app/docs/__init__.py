# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Auto-generated documentation module for appinfra.

Provides automatic documentation generation from tool definitions,
keeping docs in sync with code.

Example:
    from . import DocsGenerator

    # Generate docs for an app
    generator = DocsGenerator()
    markdown = generator.generate_all(app)
    print(markdown)

    # Generate to file
    generator.generate_to_file(app, Path("docs/cli-reference.md"))
"""

from .generator import DocsGenerator

__all__ = [
    "DocsGenerator",
]
