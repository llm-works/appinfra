# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
pylint plugin that turns off astroid's attribute inference while building modules.

For each ``obj.attr = value`` in a module, astroid infers ``obj`` and records the
attribute on what it finds (``AstroidBuilder.delayed_assattr``). Inference imports
whatever ``obj`` comes from, so one assignment on an object from a large dependency
makes pylint build thousands of that dependency's modules. The duplicate-code check
compares lines and never reads these attributes, so ``cq dup`` loads this plugin.
pylint registers plugins again in each of its worker processes.
"""

from astroid.builder import AstroidBuilder
from astroid.nodes import AssignAttr
from pylint.lint import PyLinter


def _skip_assattr(self: AstroidBuilder, node: AssignAttr) -> None:
    """Leave the assigned attribute unrecorded."""


def register(linter: PyLinter) -> None:
    """Replace astroid's attribute inference; fail if astroid no longer has it."""
    if not hasattr(AstroidBuilder, "delayed_assattr"):
        raise RuntimeError(
            "astroid.builder.AstroidBuilder.delayed_assattr is gone; "
            "cq dup's pylint plugin needs updating"
        )
    AstroidBuilder.delayed_assattr = _skip_assattr
