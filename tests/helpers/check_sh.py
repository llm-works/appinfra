# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Settings for tests that run check.sh (make check) over a fixture project."""

# One pytest worker per run. check.sh sizes its pools from the CPU count, and a fixture
# project holds a test or two: the other workers would only start and import, several times
# over while these tests run side by side in make check's own coverage run.
FIXTURE_WORKERS = {
    "APPINFRA_PYTEST_CHECK_WORKERS": "1",
    "APPINFRA_PYTEST_COVERAGE_WORKERS": "1",
}
