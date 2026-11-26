# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""What the performance tests share."""

import sys

# Share of a wall-clock rate floor enforced on macOS: its CI runners measure rates
# well under Linux runners on the same code; the full floor applies on Linux
RATE_SHARE = 0.5 if sys.platform == "darwin" else 1.0
