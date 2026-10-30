# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for appinfra.app.utils module."""

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestDisableUrllibWarnings:
    """Test disable_urllib_warnings function."""

    def test_disables_urllib3_warnings(self):
        """Test that disable_urllib_warnings calls urllib3.disable_warnings."""
        # Need to patch urllib3 module since it's imported inside the function
        with patch("urllib3.disable_warnings") as mock_disable:
            from appinfra.app.utils import disable_urllib_warnings

            disable_urllib_warnings()

            # Verify urllib3.disable_warnings() was called
            mock_disable.assert_called_once()
