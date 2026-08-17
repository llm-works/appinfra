# Test Naming Standards for Infra Framework

This document defines the standardized naming conventions for test files in the infrastructure framework. Following these conventions ensures consistent test organization and enables automated test discovery and categorization.

## 📋 **Test File Naming Conventions**

### **1. Unit Tests**
- **Pattern**: `*_test.py`
- **Purpose**: Fast, isolated tests with mocked dependencies
- **Location**: Co-located with source code
- **Examples**:
  ```
  infra/app/core/app_test.py
  infra/log/config_test.py
  infra/db/pg/pg_test.py
  ```

### **2. Integration Tests**
- **Pattern**: `*_integration_test.py`
- **Purpose**: Tests with real dependencies (database, network, etc.)
- **Location**: Co-located with source code
- **Examples**:
  ```
  infra/db/pg/pg_integration_test.py
  infra/app/tracing/tracing_integration_test.py
  infra/net/network_integration_test.py
  ```

### **3. Performance Tests**
- **Pattern**: `*_perf_test.py`
- **Purpose**: Load testing, benchmarks, scalability tests
- **Location**: Co-located with source code
- **Examples**:
  ```
  infra/app/tracing/tracing_perf_test.py
  infra/db/connection_perf_test.py
  infra/log/logging_perf_test.py
  ```

### **4. Security Tests**
- **Pattern**: `*_security_test.py`
- **Purpose**: SQL injection, XSS, input validation tests
- **Location**: Co-located with source code
- **Examples**:
  ```
  infra/app/auth/auth_security_test.py
  infra/db/input_security_test.py
  infra/net/request_security_test.py
  ```

### **5. End-to-End Tests**
- **Pattern**: `*.py` (in `/e2e` directory)
- **Purpose**: Full system workflows and user journeys
- **Location**: Centralized in `tests/e2e` directory
- **Examples**:
  ```
  tests/e2e/cli_to_database_workflow.py
  tests/e2e/logging_pipeline_e2e.py
  tests/e2e/complete_app_workflow.py
  ```

## 🎯 **Test Class Naming Conventions**

### **Base Pattern**
All test classes should follow the pattern: `Test<ComponentName><TestType>`

### **Examples by Test Type**

#### **Unit Test Classes**
```python
class TestApp(unittest.TestCase):           # Basic unit test
class TestAppConfig(unittest.TestCase):     # Component-specific
class TestLoggerFactory(unittest.TestCase): # Factory pattern
```

#### **Integration Test Classes**
```python
class TestDatabaseIntegration(IntegrationTestCase):
class TestNetworkIntegration(IntegrationTestCase):
class TestTracingIntegration(IntegrationTestCase):
```

#### **Performance Test Classes**
```python
class TestAppPerformance(PerformanceTestCase):
class TestDatabasePerformance(PerformanceTestCase):
class TestLoggingPerformance(PerformanceTestCase):
```

#### **Security Test Classes**
```python
class TestInputSecurity(SecurityTestCase):
class TestAuthSecurity(SecurityTestCase):
class TestDatabaseSecurity(SecurityTestCase):
```

#### **End-to-End Test Classes**
```python
class TestCompleteWorkflow(E2ETestCase):
class TestCLIToDatabaseWorkflow(E2ETestCase):
class TestLoggingPipelineE2E(E2ETestCase):
```

## 🏗️ **Test Method Naming Conventions**

### **Standard Pattern**
All test methods should follow the pattern: `test_<action>_<scenario>_<expected_result>`

### **Examples**

#### **Unit Test Methods**
```python
def test_create_app_success(self):
def test_create_app_with_invalid_config_raises_error(self):
def test_parse_config_with_missing_file_returns_default(self):
def test_logger_format_message_with_timestamp(self):
```

#### **Integration Test Methods**
```python
def test_database_connection_success(self):
def test_database_query_with_real_data_returns_results(self):
def test_network_request_with_timeout_handles_gracefully(self):
def test_tracing_hierarchy_preserves_context(self):
```

#### **Performance Test Methods**
```python
def test_app_startup_time_under_threshold(self):
def test_database_query_performance_at_scale(self):
def test_logging_throughput_meets_requirements(self):
def test_concurrent_access_performance(self):
```

#### **Security Test Methods**
```python
def test_sql_injection_resistance(self):
def test_xss_input_validation(self):
def test_authentication_bypass_prevention(self):
def test_malicious_input_handling(self):
```

#### **End-to-End Test Methods**
```python
def test_complete_cli_workflow(self):
def test_database_to_logging_pipeline(self):
def test_error_recovery_workflow(self):
def test_user_registration_to_login_flow(self):
```

## 📁 **Directory Structure Examples**

### **Co-located Structure (Recommended)**
```
infra/
├── app/
│   ├── core/
│   │   ├── app.py
│   │   ├── app_test.py                    # Unit tests
│   │   ├── app_integration_test.py        # Integration tests
│   │   └── app_perf_test.py              # Performance tests
│   └── tracing/
│       ├── traceable.py
│       ├── traceable_test.py              # Unit tests
│       ├── traceable_integration_test.py  # Integration tests
│       ├── traceable_perf_test.py         # Performance tests
│       └── traceable_security_test.py     # Security tests
├── db/
│   └── pg/
│       ├── pg.py
│       ├── pg_test.py                     # Unit tests
│       ├── pg_integration_test.py         # Integration tests
│       └── pg_perf_test.py               # Performance tests
└── tests/e2e/                             # Centralized E2E tests
    ├── __init__.py
    ├── cli_to_database_workflow.py
    ├── logging_pipeline_e2e.py
    └── complete_app_workflow.py
```

## 🔍 **Test Discovery Patterns**

### **Makefile Targets**
The enhanced Makefile supports different test discovery patterns:

```makefile
test.unit:        # Discovers: *_test.py
test.integration: # Discovers: *_integration_test.py  
test.perf: # Discovers: *_perf_test.py
test.security:    # Discovers: *_security_test.py
test.e2e:         # Discovers: tests/e2e/*.py
```

### **Python Discovery Commands**
```bash
# Unit tests
~/.venv/bin/python -m unittest discover -t . -p '*_test.py'

# Integration tests  
~/.venv/bin/python -m unittest discover -t . -p '*_integration_test.py'

# Performance tests
~/.venv/bin/python -m unittest discover -t . -p '*_perf_test.py'

# Security tests
~/.venv/bin/python -m unittest discover -t . -p '*_security_test.py'

# E2E tests
~/.venv/bin/python -m unittest discover -t ./tests/e2e -p '*.py'
```

## ✅ **Validation Tools**

### **Automated Validation**
Use the `tests/test_categories.py` module to validate naming conventions:

```python
from tests.test_categories import TestNamingValidator

validator = TestNamingValidator()

# Validate a single file
result = validator.validate_test_name(Path("app_test.py"))
print(f"Valid: {result['valid']}, Type: {result['test_type']}")

# Validate entire directory
results = validator.validate_directory(Path("infra/"))
for result in results:
    if not result["valid"]:
        print(f"❌ {result['file_path']}: {result['issues']}")
```

### **Manual Validation Checklist**

#### **File Names**
- [ ] Unit tests end with `_test.py`
- [ ] Integration tests end with `_integration_test.py`
- [ ] Performance tests end with `_perf_test.py`
- [ ] Security tests end with `_security_test.py`
- [ ] E2E tests are in `/e2e` directory

#### **Class Names**
- [ ] Start with `Test`
- [ ] Include component name
- [ ] Include test type for specialized tests
- [ ] Use appropriate base class

#### **Method Names**
- [ ] Start with `test_`
- [ ] Describe action, scenario, and expected result
- [ ] Use descriptive, readable names
- [ ] Follow snake_case convention

## 🚀 **Migration Guide**

### **Existing Tests**
If you have existing tests that don't follow these conventions:

#### **1. Identify Test Type**
```python
# Current: some_test.py
# Determine if it's unit, integration, performance, or security

# If it has mocked dependencies -> unit test
# If it uses real database/network -> integration test
# If it measures performance -> performance test
# If it tests security -> security test
```

#### **2. Rename Files**
```bash
# Unit tests (no change needed)
mv some_test.py component_test.py

# Integration tests
mv some_test.py component_integration_test.py

# Performance tests  
mv some_test.py component_perf_test.py

# Security tests
mv some_test.py component_security_test.py
```

#### **3. Update Base Classes**
```python
# Before
class TestSomething(unittest.TestCase):

# After (choose appropriate base class)
class TestSomething(UnitTestCase):           # For unit tests
class TestSomething(IntegrationTestCase):    # For integration tests
class TestSomething(PerformanceTestCase):    # For performance tests
class TestSomething(SecurityTestCase):       # For security tests
class TestSomething(E2ETestCase):            # For E2E tests
```

#### **4. Update Imports**
```python
# Add to existing imports
from appinfra.test_utils import (
    UnitTestCase,
    IntegrationTestCase,
    PerformanceTestCase,
    SecurityTestCase,
    E2ETestCase,
)
```

## 📊 **Benefits of Following These Standards**

### **1. Automated Test Discovery**
- Clear categorization enables targeted test execution
- CI/CD pipelines can run different test types at different stages
- Developers can quickly run relevant test subsets

### **2. Improved Maintainability**
- Consistent naming makes tests easier to find and understand
- Clear separation of concerns between test types
- Better organization reduces cognitive load

### **3. Enhanced Debugging**
- Test type is immediately apparent from file name
- Easier to identify which tests are failing and why
- Better test failure reporting and categorization

### **4. Better Performance**
- Unit tests can run quickly for immediate feedback
- Integration tests can be run less frequently
- Performance tests can be scheduled appropriately

### **5. Team Productivity**
- New team members can quickly understand test organization
- Consistent patterns reduce learning curve
- Clear expectations for where to add new tests

## 🎯 **Summary**

Following these naming standards ensures:

- **Consistency** across the entire codebase
- **Discoverability** through automated tools
- **Maintainability** for long-term development
- **Clarity** about test purpose and scope
- **Efficiency** in test execution and debugging

Use the provided validation tools to ensure compliance and maintain these standards as the codebase evolves.
