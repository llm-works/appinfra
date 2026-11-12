# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""The project the suite behavior tests judge evidence against."""

from appinfra._suite_behavior import Project

PROJECT = Project(
    root="/proj", packages=frozenset({"myapp"}), scripts=frozenset({"myapp-cli"})
)
