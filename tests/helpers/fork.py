# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Warning filter for tests that fork on purpose."""

import pytest

# Python 3.12+ warns on fork() in a multi-threaded process. In these tests the only
# other thread is the pytest-xdist worker's own; under -n 0 they fork without the
# warning. Scoped per test so that a fork from a thread appinfra starts still fails.
forks_in_xdist_worker = pytest.mark.filterwarnings(
    "ignore:This process .* is multi-threaded:DeprecationWarning"
)
