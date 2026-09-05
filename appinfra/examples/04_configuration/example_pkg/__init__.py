# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Synthetic library used by ``library_mode_from_spec.py``.

Stands in for a real appinfra consumer package that ships its default
configuration at ``<pkg>/etc/<pkg>.yaml`` per v1 config protocol rule 2.
The module name ``example_pkg`` maps to the config filename
``example-pkg.yaml`` via ``Config.from_spec``'s default derivation
(underscore → hyphen).
"""
