# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Synthetic library used by ``library_mode_config_spec.py``.

Stands in for a real appinfra consumer package that ships its default
configuration at ``<pkg>/etc/<pkg>.yaml`` per config protocol rule 2.
``ConfigSpec("example-org", "example-pkg")`` locates this module by mapping
the config name's hyphen to an underscore and derives the base config
``etc/example-pkg.yaml`` from the config name.
"""
