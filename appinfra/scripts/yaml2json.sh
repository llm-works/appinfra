#!/usr/bin/env python3

# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

import sys, yaml, json
y=yaml.safe_load(sys.stdin.read())
print(json.dumps(y))
