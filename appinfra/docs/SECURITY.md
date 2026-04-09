# Security Policy

## Reporting Security Vulnerabilities

**We take security seriously.** If you discover a security vulnerability in this framework, please
report it responsibly.

### How to Report

**DO NOT** open a public GitHub issue for security vulnerabilities.

Instead, use GitHub's private vulnerability reporting:
1. Go to the repository's **Security** tab
2. Click **"Report a vulnerability"**
3. Submit your confidential report

### What to Include

Please include the following information in your report:

- **Description** of the vulnerability
- **Steps to reproduce** the issue
- **Potential impact** assessment
- **Suggested fix** (if you have one)
- **Your contact information** for follow-up

### Response Timeline

- **Initial Response:** Within 48 hours
- **Triage & Assessment:** Within 7 days
- **Fix & Disclosure:** Coordinated with reporter (typically 30-90 days)

### Recognition

We maintain a security hall of fame for responsible disclosure. Contributors will be credited
(unless they prefer to remain anonymous).

---

## Supported Versions

| Version | Supported          | End of Support |
| ------- | ------------------ | -------------- |
| 0.1.x   | :white_check_mark: | TBD            |

**Note:** This is a pre-1.0 release. Security patches will be provided for the latest 0.1.x version
only.

---

## Security Features

The framework includes multiple layers of security protection:

### 1. YAML Security

**Protection against arbitrary code execution and path traversal attacks.**

#### Safe YAML Loading
- Uses `yaml.SafeLoader` exclusively (never `yaml.Loader`)
- Prevents arbitrary Python object instantiation
- Blocks `!!python/object` tags

```python
# ✅ SAFE - Uses SafeLoader
from appinfra import Config
config = Config('etc/config.yaml')

# ❌ UNSAFE - Never do this
import yaml
with open('config.yaml') as f:
    yaml.load(f, Loader=yaml.Loader)  # DANGEROUS!
```

#### Path Traversal Protection
- Validates all `!include` paths
- Restricts includes to project root
- Prevents `../../../etc/passwd` attacks

```python
# Automatic protection when using project_root
from appinfra.yaml import Loader
from pathlib import Path

loader = Loader(
    stream,
    current_file=config_file,
    project_root=Path.cwd()  # Restricts includes to current directory and below
)
```

#### Circular Include Detection
- Detects and prevents infinite include loops
- Maximum include depth: 10 levels (configurable)

**Example Attack Blocked:**
```yaml
# file1.yaml
data: !include file2.yaml

# file2.yaml
data: !include file1.yaml  # ❌ BLOCKED: Circular include
```

### 2. Regular Expression (ReDoS) Protection

**Protection against Regular Expression Denial of Service attacks.**

The framework includes comprehensive ReDoS protection for all user-provided regex patterns.

#### Pattern Complexity Validation
- Detects nested quantifiers: `(.+)+`, `(.*)*`
- Validates maximum pattern length (1000 chars)
- Rejects catastrophic backtracking patterns

#### Timeout Mechanisms
- 1-second default timeout for regex operations
- Prevents infinite loops from malicious patterns
- Unix systems only (Windows degrades gracefully)

```python
from appinfra import safe_compile, RegexTimeoutError, RegexComplexityError

try:
    # Safe: Protected against ReDoS
    pattern = safe_compile(user_input, timeout=1.0)
    match = pattern.match(data)
except RegexComplexityError:
    log.error("Pattern too complex - possible ReDoS attack")
except RegexTimeoutError:
    log.error("Pattern matching timed out")
```

**Internal patterns are pre-validated** and safe. Only use `safe_compile()` for user-provided
patterns.

### 3. SQL Injection Protection

**Protection via SQLAlchemy ORM and parameterized queries.**

- All database queries use SQLAlchemy's parameter binding
- Raw SQL not exposed in public APIs
- Connection pooling prevents resource exhaustion

```python
from appinfra import PG
import sqlalchemy as sa

pg = PG('etc/config.yaml', 'production')

# ✅ SAFE - Parameterized query
with pg.session() as session:
    result = session.execute(
        sa.text("SELECT * FROM users WHERE id = :user_id"),
        {"user_id": user_input}  # Safe parameter binding
    )

# ❌ UNSAFE - String concatenation
with pg.session() as session:
    result = session.execute(
        sa.text(f"SELECT * FROM users WHERE id = {user_input}")  # DANGEROUS!
    )
```

### 4. Input Validation

**Validation at system boundaries.**

The framework validates inputs at critical points:

- **Tool names:** `^[a-z][a-z0-9_-]*$` (prevents shell injection)
- **Time formats:** Strict validation (`HH:MM`, bounded ranges)
- **Duration strings:** Validated against known units
- **Configuration keys:** Alphanumeric + dot + underscore only

```python
# Tool name validation (infra/app/tools/registry.py)
if not re.match(r"^[a-z][a-z0-9_-]*$", tool_name):
    raise ValueError(f"Invalid tool name: {tool_name}")

# Duration validation
from appinfra import delta_to_secs
from appinfra.time.delta import InvalidDurationError

try:
    seconds = delta_to_secs(user_input)  # Validates format
except InvalidDurationError:
    log.error("Invalid duration format")
```

### 5. Credential Management

**Best practices for handling sensitive data.**

The framework follows secure credential handling:

- **Never hardcode credentials** in configuration files
- Use **environment variables** for sensitive data
- Support for **external secret managers** (AWS Secrets Manager, HashiCorp Vault)

```python
# ✅ GOOD - Environment variable override
# etc/config.yaml
database:
  host: localhost
  port: 5432
  # username and password from environment

# Shell:
export INFRA_DATABASE_USERNAME=dbuser
export INFRA_DATABASE_PASSWORD=secret123

# Code:
from appinfra import Config
config = Config('etc/config.yaml')
# Credentials automatically loaded from environment
```

**Never commit:**
- `.env` files
- `credentials.json`
- Files with `secret`, `password`, `key` in the name
- Database connection strings with embedded credentials

### 6. Resource Limits

**Protection against resource exhaustion attacks.**

- **YAML include depth:** Maximum 10 levels
- **Regex pattern length:** Maximum 1000 characters
- **Regex operation timeout:** 1 second default
- **Database connection pooling:** Prevents connection exhaustion
- **Rate limiting:** Available via `RateLimiter` utility

```python
from appinfra.rate_limit import RateLimiter
from appinfra.log import Logger

lg = Logger("my_app")
limiter = RateLimiter(lg, per_minute=10)  # 10 calls per minute

def expensive_operation():
    limiter.next()  # blocks until next slot is available
    # Protected operation
```

---

## Security Best Practices

Follow these practices when using the framework:

### Configuration Security

#### 1. Use Environment Variables for Secrets

```yaml
# ✅ GOOD
database:
  host: ${DATABASE_HOST}
  username: ${DATABASE_USER}
  password: ${DATABASE_PASSWORD}

# ❌ BAD
database:
  host: prod-db.example.com
  username: admin
  password: supersecret123  # NEVER DO THIS
```

#### 2. Restrict File Permissions

```bash
# Configuration files should not be world-readable
chmod 600 etc/config.yaml
chmod 600 etc/credentials.json
```

#### 3. Validate Includes with project_root

```python
from pathlib import Path
from appinfra.yaml import load

# ✅ GOOD - Restricts includes to /app/config and below
with open('/app/config/config.yaml') as f:
    config = load(f, current_file=Path('/app/config/config.yaml'), project_root=Path('/app/config'))

# ❌ RISKY - No path restrictions (and relative !include/!path won't resolve)
with open('config.yaml') as f:
    config = load(f)  # Allows any file system access
```

### Application Security

#### 1. Validate All User Input

```python
from appinfra.time.delta import delta_to_secs, InvalidDurationError

def set_timeout(user_input: str):
    try:
        # Validate before use
        timeout = delta_to_secs(user_input)
        if timeout > 3600:  # Additional business logic validation
            raise ValueError("Timeout cannot exceed 1 hour")
        return timeout
    except InvalidDurationError:
        raise ValueError(f"Invalid duration format: {user_input}")
```

#### 2. Use Safe Regex for User Patterns

```python
from appinfra import safe_compile

def add_filter(user_pattern: str):
    try:
        # ✅ GOOD - Protected against ReDoS
        pattern = safe_compile(user_pattern, timeout=1.0)
        return pattern
    except Exception as e:
        log.error(f"Invalid pattern: {e}")
        raise ValueError("Invalid filter pattern")
```

#### 3. Sanitize Log Output

```python
import logging

lg = logging.getLogger(__name__)

def process_request(user_id: str):
    # ⚠️ Be careful logging user input - could leak sensitive data
    # or inject log formatting characters
    safe_user_id = user_id.replace('\n', '').replace('\r', '')
    lg.info(f"Processing request for user: {safe_user_id}")
```

#### 4. Use Structured Logging for Sensitive Data

```python
from appinfra import LoggingBuilder

logger = (
    LoggingBuilder("app")
    .with_level("info")
    .json_handler()  # Structured logging prevents injection
    .build()
)

# User input is properly escaped in JSON
logger.info("Login attempt", extra={
    "user": user_input,  # Safely escaped
    "ip": request.ip
})
```

### Database Security

#### 1. Use Read-Only Connections Where Appropriate

```python
from appinfra import PG

pg = PG('etc/config.yaml', 'production')

# Read-only connection for queries
with pg.session_ro() as session:
    results = session.execute(query)  # Cannot modify data
```

#### 2. Use Connection Pooling

```python
# Connection pooling is enabled by default
# Prevents resource exhaustion and connection leak attacks
pg = PG('etc/config.yaml', 'production')
# Automatic pooling with sensible defaults
```

#### 3. Enable Query Logging in Development

```python
# etc/config.yaml
database:
  echo: true  # Log all SQL queries (development only!)
  echo_pool: true  # Log connection pool events
```

**⚠️ Never enable `echo: true` in production** - logs may contain sensitive data.

### Network Security

#### 1. Use TLS for Database Connections

```yaml
# etc/config.yaml
database:
  sslmode: require
  sslrootcert: /path/to/ca.crt
```

#### 2. Validate Server Certificates

```python
# PostgreSQL SSL configuration
database:
  sslmode: verify-full  # Verify server identity
  sslcert: /path/to/client.crt
  sslkey: /path/to/client.key
```

---

## Threat Model

### In Scope

The framework protects against:

- **Arbitrary code execution** (YAML, SQL injection)
- **Path traversal attacks** (YAML includes)
- **ReDoS attacks** (malicious regex patterns)
- **Resource exhaustion** (connection pools, rate limiting)
- **Credential leakage** (environment-based config)
- **Log injection** (structured logging)

### Out of Scope

The framework **does not** protect against:

- **Memory exhaustion** from extremely large files (user responsibility)
- **Network-level attacks** (DDoS, packet manipulation)
- **Operating system vulnerabilities** (patch your systems)
- **Side-channel attacks** (timing, spectre/meltdown)
- **Physical access** to servers or credentials

### Assumptions

The framework assumes:

- **Trusted administrators** managing configuration files
- **Secure deployment environment** (proper file permissions, network isolation)
- **Regular updates** to Python and dependencies
- **Proper secret management** (not committing credentials)

---

## Security Checklist

Use this checklist when deploying applications:

### Pre-Deployment

- [ ] Review all configuration files for hardcoded credentials
- [ ] Ensure sensitive files have restrictive permissions (600)
- [ ] Enable TLS/SSL for database connections
- [ ] Set appropriate resource limits (connection pools, timeouts)
- [ ] Validate all user-provided regex patterns with `safe_compile()`
- [ ] Use `project_root` parameter for YAML includes
- [ ] Review logging configuration (no sensitive data in logs)

### Deployment

- [ ] Use environment variables for all secrets
- [ ] Disable `echo: true` in database configuration
- [ ] Configure appropriate log levels (INFO or WARNING for production)
- [ ] Enable connection pooling for databases
- [ ] Set up monitoring and alerting for security events
- [ ] Document security configuration in deployment guide

### Post-Deployment

- [ ] Regularly update Python and dependencies
- [ ] Monitor security advisories for dependencies
- [ ] Review logs for suspicious patterns
- [ ] Conduct periodic security audits
- [ ] Test backup and recovery procedures
- [ ] Rotate credentials regularly

---

## Common Vulnerabilities and Mitigations

### 1. Configuration File Exposure

**Risk:** Config files containing secrets exposed via web server misconfiguration.

**Mitigation:**
- Store configs outside web root
- Use environment variables for secrets
- Restrict file permissions (600)
- Add config files to `.gitignore`

### 2. Log Injection

**Risk:** User input containing newlines can forge log entries.

**Mitigation:**
```python
# ✅ GOOD - Use structured logging
logger.info("User login", extra={"user": user_input})

# ❌ BAD - String formatting
logger.info(f"User login: {user_input}")  # Can inject newlines
```

### 3. Path Traversal in Includes

**Risk:** Malicious YAML files include sensitive system files.

**Mitigation:**
```python
# ✅ GOOD - Restrict to project root
from pathlib import Path
from appinfra.yaml import load

with open('/app/config/config.yaml') as f:
    config = load(f, current_file=Path('/app/config/config.yaml'), project_root=Path('/app/config'))

# ❌ RISKY - No restrictions (and relative !include/!path won't resolve)
with open('config.yaml') as f:
    config = load(f)
```

### 4. SQL Injection

**Risk:** User input concatenated into SQL queries.

**Mitigation:**
```python
# ✅ GOOD - Parameter binding
session.execute(
    sa.text("SELECT * FROM users WHERE name = :name"),
    {"name": user_input}
)

# ❌ BAD - String formatting
session.execute(sa.text(f"SELECT * FROM users WHERE name = '{user_input}'"))
```

### 5. ReDoS Attacks

**Risk:** Malicious regex patterns cause CPU exhaustion.

**Mitigation:**
```python
# ✅ GOOD - Use safe_compile for user input
from appinfra import safe_compile
pattern = safe_compile(user_pattern, timeout=1.0)

# ❌ BAD - Direct compilation
import re
pattern = re.compile(user_pattern)  # Vulnerable to ReDoS
```

---

## Dependency Security

### Monitoring Dependencies

We use the following tools to monitor dependency security:

- **GitHub Dependabot** - Automated dependency updates
- **pip-audit** - Vulnerability scanning for Python packages
- **Safety** - Checks for known security vulnerabilities

### Updating Dependencies

```bash
# Check for vulnerable dependencies
pip-audit

# Update specific dependency
pip install --upgrade package-name

# Update all dependencies (test thoroughly!)
pip install --upgrade -r requirements.txt
```

### Pinning Dependencies

The framework pins dependencies to prevent supply chain attacks:

```toml
# pyproject.toml
dependencies = [
    "sqlalchemy>=2.0.0,<3.0.0",  # Pinned with upper bound
    "PyYAML>=6.0,<7.0",
]
```

---

## Security Updates

### Notification Methods

Security updates are announced via:

1. **GitHub Security Advisories** (recommended)
2. **Release Notes** (for all releases)
3. **Email** (if you've subscribed to security notifications)

### Update Policy

- **Critical vulnerabilities:** Patched within 7 days
- **High severity:** Patched within 30 days
- **Medium severity:** Patched in next minor release
- **Low severity:** Patched in next major release

---

## Resources

### Internal Documentation

- [Configuration Guide](docs/guides/environment-variables.md) - Secure config practices
- [Logging Guide](docs/guides/logging-builder.md) - Structured logging
- [Testing Guide](docs/guides/test-naming-standards.md) - Security testing

### External Resources

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [CWE: Common Weakness Enumeration](https://cwe.mitre.org/)
- [Python Security Best Practices](https://python.readthedocs.io/en/stable/library/security_warnings.html)
- [SQLAlchemy Security](https://docs.sqlalchemy.org/en/20/faq/security.html)

---

## Contact

For security-related questions or concerns:

- **Security Issues:** Use GitHub's private vulnerability reporting (Security tab → Report a vulnerability)
- **General Questions:** GitHub Discussions (public)
- **Documentation:** See docs/ directory

---

**Last Updated:** 2025-11-27
**Version:** 0.1.0
