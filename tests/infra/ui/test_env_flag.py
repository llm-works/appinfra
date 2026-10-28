# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.ui._env.env_flag, the boolean environment setting rule."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from appinfra.ui._env import env_flag

TRUE = ["true", "1", "y", "yes", "TRUE", "Y", "Yes"]
FALSE = ["false", "0", "n", "no", "FALSE", "No"]


@pytest.mark.unit
class TestEnvFlag:
    @pytest.mark.parametrize("value", TRUE)
    def test_true_values(self, value: str) -> None:
        with patch.dict(os.environ, {"APPINFRA_YES": value}):
            assert env_flag("APPINFRA_YES") is True

    @pytest.mark.parametrize("value", FALSE)
    def test_false_values(self, value: str) -> None:
        with patch.dict(os.environ, {"APPINFRA_YES": value}):
            assert env_flag("APPINFRA_YES") is False

    def test_unset_is_false(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert env_flag("APPINFRA_YES") is False

    @pytest.mark.parametrize("value", ["", "ture", "on", "2", "yes no"])
    def test_other_values_raise(self, value: str) -> None:
        with (
            patch.dict(os.environ, {"APPINFRA_YES": value}),
            pytest.raises(ValueError, match="APPINFRA_YES=.* is not a boolean"),
        ):
            env_flag("APPINFRA_YES")
