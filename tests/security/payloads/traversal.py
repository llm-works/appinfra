# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Path traversal attack payloads for security testing."""

# Classic Path Traversal Payloads
# These payloads attempt to escape directory boundaries using relative paths
CLASSIC_TRAVERSAL = [
    "../../../etc/passwd",
    "../../../etc/shadow",
    "..\\..\\..\\windows\\system32\\config\\sam",
    "....//....//....//etc/passwd",  # Double slash variant
    "..%2F..%2F..%2Fetc%2Fpasswd",  # URL encoded
    "..%252F..%252F..%252Fetc%252Fpasswd",  # Double URL encoded
    "../../../../../../etc/passwd",  # Many levels
    "./../.../.././../etc/passwd",  # Mixed separators
    "..;/..;/..;/etc/passwd",  # Semicolon separator (some parsers)
]

# Absolute Path Escape Payloads
# These payloads attempt to access files using absolute paths
ABSOLUTE_PATH_ESCAPE = [
    "/etc/passwd",
    "/etc/shadow",
    "/root/.ssh/id_rsa",
    "C:\\Windows\\System32\\config\\SAM",
    "C:\\Windows\\win.ini",
    "//etc/passwd",  # UNC-style
    "file:///etc/passwd",  # File URL scheme
    "/var/log/syslog",
    "/proc/self/environ",  # Process environment variables
]

# Null Byte Bypass Payloads
# These payloads attempt to bypass extension checks using null bytes
NULL_BYTE_BYPASS = [
    "../../../etc/passwd\x00.yaml",
    "/etc/shadow\x00allowed.conf",
    "malicious\x00.txt",
    "../../sensitive\x00.log",
]

# Symlink Attack Payloads
# These are file names that might be used in symlink attacks
SYMLINK_TARGETS = [
    "/etc/passwd",
    "/root/.ssh/authorized_keys",
    "/var/log/auth.log",
    "../../../sensitive_file",
]

# Combined Encoding Attacks
# These payloads use multiple encoding techniques to bypass filters
ENCODED_TRAVERSAL = [
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",  # URL encoded
    "..%c0%af..%c0%af..%c0%afetc%c0%afpasswd",  # Overlong UTF-8
    "%252e%252e%252f%252e%252e%252f%252e%252e%252fetc%252fpasswd",  # Double encoded
    "..%5c..%5c..%5cwindows%5csystem32%5cconfig%5csam",  # Windows backslash encoded
]
