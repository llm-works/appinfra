# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Injection attack payloads for security testing."""

# YAML Code Execution Payloads
# These payloads attempt to execute arbitrary Python code via YAML parsing
YAML_CODE_EXECUTION = [
    "!!python/object/apply:os.system ['echo pwned']",
    "!!python/object/new:os.system ['id']",
    "!!python/object/apply:subprocess.check_output [['whoami']]",
    "!!python/object/new:subprocess.Popen [['malicious']]",
    '!!python/object/apply:eval [\'__import__("os").system("malicious")\']',
]

# Shell Injection Payloads
# These payloads attempt command injection via shell metacharacters
SHELL_INJECTION = [
    "tool; rm -rf /",
    "tool | cat /etc/passwd",
    "tool && whoami",
    "tool || id",
    "tool`id`",
    "tool$(whoami)",
    "tool\nmalicious_command",
    "tool\rmalicious_command",
    "tool & background_process",
    "tool > /dev/null",
    "tool < /etc/shadow",
    "tool; echo 'pwned' >> ~/.bashrc",
]

# Environment Variable Injection Payloads
# These payloads attempt code execution via environment variable values
ENV_VAR_INJECTION = [
    "${__import__('os').system('malicious')}",
    "${eval('malicious')}",
    "$(malicious)",
    "`whoami`",
    "$((1+1))",  # Arithmetic expansion
    "${PATH}; malicious",
]

# Log Injection Payloads
# These payloads attempt to inject fake log entries or ANSI escape codes
LOG_INJECTION = [
    "message\n[CRITICAL] Fake critical error - system compromised",
    "msg\x1b[31mRed text attack\x1b[0m",
    "msg\r\nHTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html>fake</html>",
    "log_entry\n[ERROR] Admin password: fake123",
    "user_input\x00hidden_content",  # Null byte injection
    "\x1b]0;Fake Window Title\x07",  # Terminal escape sequence
]

# SQL Injection Payloads (for database security tests)
SQL_INJECTION = [
    "'; DROP TABLE users--",
    "' OR '1'='1",
    "' OR '1'='1'--",
    "admin'--",
    "' UNION SELECT * FROM sensitive_data--",
    "1'; DELETE FROM logs WHERE '1'='1",
    "' OR 1=1#",
    "admin' /*",
    "' OR 'x'='x",
]
