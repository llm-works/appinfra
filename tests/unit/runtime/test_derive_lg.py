# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""spawn(derive_lg=...) refuses a suffix that is no logger name's, before the
runtime is asked anything: the runtime here is not even running."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from appinfra.runtime import Runtime


@pytest.mark.parametrize("suffix", [3, b"worker", ["worker"]])
def test_a_suffix_must_be_a_string(suffix: object) -> None:
    with pytest.raises(TypeError, match="derive_lg must be a string"):
        Runtime(MagicMock()).spawn(abs, 1, derive_lg=suffix)  # type: ignore[arg-type]


def test_a_suffix_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        Runtime(MagicMock()).spawn(abs, 1, derive_lg="")
