# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors


def disable_urllib_warnings() -> None:
    import urllib3

    urllib3.disable_warnings()
