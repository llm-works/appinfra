# Configuration-Based Logging for Tests

Create test loggers that automatically use configuration from `etc/infra.yaml`.

## Configuration

In `etc/infra.yaml`:
```yaml
test:
  logging:
    level: error  # or "false" to disable completely
    location: 1
    micros: true
    colors_enabled: false
```

## Usage

### Simple (Recommended)
```python
import unittest
from appinfra.test_helpers import create_test_logger


class TestExample(unittest.TestCase):
    def setUp(self):
        self.logger = create_test_logger("test_logger")

    def test_something(self):
        self.logger.error("This will be logged")
        self.logger.info("This will NOT be logged (level=error in config)")
```

### With Fallback
```python
from appinfra.test_helpers import create_test_logger_with_fallback

self.logger = create_test_logger_with_fallback(
    "test_logger"
)  # Falls back to INFO if no config
```

### Different Config Sections
```python
# Use main logging config
main_logger = create_test_logger("main", config_section="logging")

# Use test logging config
test_logger = create_test_logger("test", config_section="test.logging")
```

### Disable Logging
```python
# In config file
test:
  logging:
    level: false

# Or programmatically
from appinfra.log import LogConfig, LoggerFactory

config = LogConfig.from_params("false", location=1, micros=True)
logger = LoggerFactory.create("disabled_logger", config)
```

## Benefits

- **Centralized**: All test logging in one config file
- **Consistent**: Same behavior across all tests
- **Flexible**: Different configs for different environments
- **Simple**: One-line logger creation