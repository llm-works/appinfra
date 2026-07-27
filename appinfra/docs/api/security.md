# Security

Automatic secret detection and masking for logs and console output. Security by default - secrets
are masked without requiring explicit configuration.

## SecretMasker

Detect and mask secrets in strings using regex patterns.

```python
class SecretMasker:
    DEFAULT_MASK = "[MASKED]"

    def __init__(
        self,
        *,
        patterns: list[str] | None = None,  # Default: DEFAULT_PATTERNS
        mask: str = DEFAULT_MASK,  # Replacement string
        enabled: bool = True,  # Enable/disable masking
    ): ...

    def mask(self, text: str) -> str: ...
    def is_secret(self, text: str) -> bool: ...
    def add_pattern(self, pattern: str) -> None: ...
    def add_known_secret(self, secret: str | None) -> None: ...
    def remove_known_secret(self, secret: str) -> None: ...
    def clear_known_secrets(self) -> None: ...
```

**Basic Usage:**

```python
from appinfra.security import SecretMasker, get_masker

# Get the global masker (singleton)
masker = get_masker()

# Pattern-based masking (automatic)
text = "api_key=sk-12345678901234567890"
safe = masker.mask(text)
# "api_key=[MASKED]"

# Known secret masking (explicit)
masker.add_known_secret("my-secret-password")
text = "connecting with my-secret-password"
safe = masker.mask(text)
# "connecting with [MASKED]"
```

**Custom Masker Instance:**

```python
from appinfra.security import SecretMasker

# Create with custom settings
masker = SecretMasker(mask="<REDACTED>", enabled=True)

# Add custom patterns
masker.add_pattern(r"MY_TOKEN_[A-Z0-9]+")
```

## Global Masker Functions

```python
from appinfra.security import get_masker, reset_masker

# Get or create global instance
masker = get_masker()

# Reset global instance (useful in tests)
reset_masker()
```

## SecretMaskingFilter

Logging filter that automatically masks secrets in log messages.

```python
from appinfra.security import SecretMaskingFilter, get_masker
import logging

# Add to a logger
logger = logging.getLogger("myapp")
logger.addFilter(SecretMaskingFilter(get_masker()))

# Secrets are now automatically masked
logger.info("Connecting with password=super-secret-pass-123")
# Output: "Connecting with password=[MASKED]"
```

**Convenience Function:**

```python
from appinfra.security.filter import add_masking_filter_to_logger

# By name
add_masking_filter_to_logger("myapp")

# By instance
logger = logging.getLogger("myapp")
add_masking_filter_to_logger(logger)
```

## Default Patterns

The following secret patterns are detected by default:

| Pattern | Description | Example |
|---------|-------------|---------|
| API keys | Generic `api_key=xxx` patterns | `api_key=sk-12345...` |
| Passwords | `password=xxx`, `passwd=xxx`, `pwd=xxx` | `password=secret123` |
| Secrets/Tokens | `secret=xxx`, `token=xxx` | `token=abc123...` |
| Bearer tokens | `Bearer xxx` in auth headers | `Bearer eyJhbGc...` |
| Basic auth | `Basic xxx` base64 credentials | `Basic dXNlcjpw...` |
| AWS Access Key | `AKIA...` (20 chars) | `AKIAIOSFODNN7EXAMPLE` |
| AWS Secret Key | `aws_secret_access_key=xxx` | 40-char base64-ish string |
| GitHub tokens | `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_` | `ghp_xxxx...` |
| Slack tokens | `xoxb-`, `xoxp-`, `xoxa-` | `xoxb-xxxx...` |
| Stripe keys | `sk_live_`, `sk_test_`, `pk_live_`, `pk_test_` | `sk_live_xxxx...` |
| Private keys | `-----BEGIN PRIVATE KEY-----` | PEM headers |
| JWT tokens | `eyJ...` with two dots | `eyJhbGc.eyJzdW.xxx` |
| Database URLs | URLs with credentials | `postgresql://user:pass@host` |

## Custom Patterns

Add patterns for application-specific secrets:

```python
from appinfra.security import get_masker

masker = get_masker()

# Add custom pattern (regex with capture group)
masker.add_pattern(r"MYAPP_SECRET_([A-Za-z0-9]{32})")
```

**Pattern Guidelines:**

- Patterns should capture the secret value as a group
- The last non-empty group will be masked
- Use `(?i)` for case-insensitive matching

## Service-Specific Patterns

Additional patterns available for specific services:

```python
from appinfra.security.patterns import SERVICE_PATTERNS

# Available services: google, azure, sendgrid, twilio
SERVICE_PATTERNS["google"]  # Google API keys, OAuth client IDs
SERVICE_PATTERNS["azure"]  # Azure storage keys
SERVICE_PATTERNS["sendgrid"]  # SendGrid API keys
SERVICE_PATTERNS["twilio"]  # Twilio API keys
```

## Aggressive Patterns

Higher false-positive patterns for maximum security:

```python
from appinfra.security.patterns import AGGRESSIVE_PATTERNS

# Matches:
# - Any 32+ char hex string
# - Any 40+ char base64 string
```

## Integration with Logging

The security module integrates automatically with appinfra's logging system. When using
`LoggingBuilder`, secret masking is applied by default.

```python
from appinfra.log import LoggingBuilder

logger = LoggingBuilder("myapp").with_level("info").console_handler().build()

# Secrets automatically masked in log output
logger.info("User authenticated with api_key=sk-live-xxxxxxxxxxxx")
# Output: "User authenticated with api_key=[MASKED]"
```

## Disabling Masking

For debugging or development:

```python
from appinfra.security import get_masker

masker = get_masker()
masker.enabled = False  # Disable masking

# Or create disabled instance
from appinfra.security import SecretMasker

masker = SecretMasker(enabled=False)
```

## See Also

- [Logging System](logging.md) - Logging with automatic secret masking
- [Configuration](utilities.md#config) - Environment variable handling
