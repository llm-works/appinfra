# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Boolean environment settings (APPINFRA_YES, APPINFRA_NON_INTERACTIVE)."""

import os

# One rule for every on/off setting, the same as Makefile.config's and
# scripts/_bool.sh's; compared case-insensitively. Unset means off; set but
# empty is an error, as in Makefile.config.
TRUE_VALUES = frozenset({"true", "1", "y", "yes"})
FALSE_VALUES = frozenset({"false", "0", "n", "no"})


def env_flag(name: str) -> bool:
    """Whether the boolean environment setting ``name`` is on; unset is off.

    Raises:
        ValueError: The value is neither in ``TRUE_VALUES`` nor ``FALSE_VALUES``.
    """
    if name not in os.environ:
        return False
    value = os.environ[name].strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValueError(
        f"{name}={os.environ[name]!r} is not a boolean: "
        "use true, 1, y, yes or false, 0, n, no"
    )
