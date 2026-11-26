# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""spawn(process=True) refusals, checked before any task or process exists."""

from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Runtime


async def parked() -> None:
    """An async function: it runs on the loop, which a child does not have."""


def test_an_async_function_is_refused_a_process() -> None:
    with pytest.raises(TypeError, match="not in a process"):
        Runtime(MagicMock()).spawn(parked, process=True)
