# End-to-End Test Suite

This directory contains end-to-end (E2E) tests for the infrastructure framework. These tests validate complete system workflows and user journeys to ensure all components work together correctly.

## 🎯 **Purpose**

E2E tests serve as the final validation layer, ensuring that:
- All system components integrate correctly
- Complete user workflows function as expected
- Real-world scenarios are properly handled
- The system behaves correctly under realistic conditions

## 🏗️ **Test Structure**

### **Base Class**
All E2E tests should inherit from `E2ETestCase`:

```python
from appinfra.test_utils import E2ETestCase


class TestCompleteWorkflow(E2ETestCase):
    def test_cli_to_database_workflow(self):
        # Test complete user journey
        pass
```

### **Test Organization**
- **File naming**: `<workflow_name>.py` (no special suffix needed)
- **Class naming**: `Test<WorkflowName>`
- **Method naming**: `test_<workflow_description>`

## 📋 **Current Test Categories**

### **1. CLI to Database Workflows**
- File: `cli_to_database_workflow.py`
- Purpose: Test complete CLI command execution that interacts with database
- Scenarios: Configuration loading, database operations, result output

### **2. Logging Pipeline E2E**
- File: `logging_pipeline_e2e.py`
- Purpose: Test complete logging system from configuration to output
- Scenarios: Multi-handler logging, file rotation, error handling

### **3. Complete Application Lifecycle**
- File: `complete_app_workflow.py`
- Purpose: Test full application startup, operation, and shutdown
- Scenarios: App initialization, tool execution, cleanup

## 🚀 **Running E2E Tests**

### **Using Make**
```bash
# Run all E2E tests
make test.e2e

# Run E2E tests with verbose output
make test.e2e.v

# Run E2E tests as part of full test suite
make test.all
```

### **Using Python Directly**
```bash
# Run all E2E tests
~/.venv/bin/python -m unittest discover -t ./tests/e2e -p '*.py'

# Run specific E2E test
~/.venv/bin/python -m unittest tests.e2e.cli_to_database_workflow

# Run with verbose output
~/.venv/bin/python -m unittest discover -t ./tests/e2e -p '*.py' -v
```

## 🛠️ **Writing E2E Tests**

### **Template Structure**
```python
"""
E2E test for [workflow description].

This test validates [specific workflow] by [test approach].
"""

import unittest
from appinfra.test_utils import E2ETestCase


class Test[WorkflowName](E2ETestCase):
    """E2E tests for [workflow description]."""

    def setUp(self):
        """Set up E2E test environment."""
        super().setUp()
        # Add workflow-specific setup
        self.add_workflow_step("setup", {"description": "Test initialization"})

    def test_[workflow_description](self):
        """Test [specific workflow scenario]."""
        # Step 1: Initial setup
        self.add_workflow_step("step_1", {"action": "initial_setup"})

        # Step 2: Main workflow
        self.add_workflow_step("step_2", {"action": "main_workflow"})

        # Step 3: Validation
        self.add_workflow_step("step_3", {"action": "validation"})

        # Add cleanup if needed
        self.add_system_cleanup(cleanup_function)

        # Assertions
        self.assertTrue(workflow_successful)

    def tearDown(self):
        """Clean up after E2E test."""
        super().tearDown()
```

### **Best Practices**

#### **1. Use Workflow Steps**
```python
def test_complex_workflow(self):
    self.add_workflow_step("database_setup", {"tables_created": 3})
    self.add_workflow_step("cli_execution", {"command": "app --config test.yaml"})
    self.add_workflow_step("result_validation", {"expected_rows": 10})
```

#### **2. Add System Cleanup**
```python
def test_with_resources(self):
    # Create test database
    test_db = create_test_database()
    self.add_system_cleanup(lambda: test_db.drop())
    
    # Create test files
    test_file = create_test_file()
    self.add_system_cleanup(os.remove, test_file)
```

#### **3. Handle Long-Running Operations**
```python
def test_long_workflow(self):
    import time
    
    # Set realistic timeout expectations
    start_time = time.time()
    
    # Perform long-running operation
    result = perform_complex_operation()
    
    # Validate timing
    execution_time = time.time() - start_time
    self.assertLess(execution_time, 60, "Workflow should complete within 60 seconds")
```

#### **4. Test Error Recovery**
```python
def test_error_recovery_workflow(self):
    # Simulate error condition
    self.add_workflow_step("error_simulation", {"error_type": "database_unavailable"})
    
    # Test recovery
    self.add_workflow_step("recovery_attempt", {"retry_count": 3})
    
    # Validate recovery
    self.add_workflow_step("recovery_validation", {"status": "recovered"})
```

## 🔧 **Configuration**

E2E tests use enhanced configuration from `etc/infra.yaml`:

```yaml
test:
  e2e_tests:
    timeout: 300  # 5 minutes
    cleanup_on_success: true
    cleanup_on_failure: false
    log_level: "INFO"
    parallel_execution: false
```

## 📊 **Test Reporting**

E2E tests provide detailed reporting:

```
E2E test test_cli_to_database_workflow completed in 45.32s with 8 steps
Workflow steps:
  1. setup (0.12s)
  2. database_setup (2.34s) 
  3. cli_execution (15.67s)
  4. result_validation (1.23s)
  5. cleanup (0.89s)
```

## ⚡ **Performance Considerations**

### **Execution Time**
- E2E tests are expected to be slow (minutes, not seconds)
- Set realistic timeout expectations
- Use workflow steps to track progress

### **Resource Usage**
- E2E tests may use significant system resources
- Run sequentially to avoid resource conflicts
- Clean up resources properly

### **CI/CD Integration**
- E2E tests may be run separately from unit/integration tests
- Consider running on dedicated test environments
- May require special infrastructure setup

## 🚨 **Troubleshooting**

### **Test Timeouts**
If tests are timing out:
1. Check if external services are available
2. Increase timeout in test configuration
3. Break complex workflows into smaller steps
4. Use workflow steps to identify bottlenecks

### **Resource Conflicts**
If tests are failing due to resource conflicts:
1. Ensure proper cleanup in tearDown
2. Use unique resource names (timestamps, UUIDs)
3. Check for leftover resources from previous runs
4. Run tests sequentially

### **Environment Issues**
If tests are failing due to environment:
1. Verify all required services are running
2. Check configuration file paths and values
3. Ensure proper permissions for file/database access
4. Validate network connectivity

## 📚 **Examples**

See the example E2E tests in this directory:
- `cli_to_database_workflow.py` - Complete CLI to database workflow
- `logging_pipeline_e2e.py` - End-to-end logging validation
- `complete_app_workflow.py` - Full application lifecycle testing

Each example demonstrates different aspects of E2E testing and can serve as templates for new tests.

## 📖 **Additional Documentation**

For comprehensive information about the test system:
- [`docs/guides/test-naming-standards.md`](../docs/guides/test-naming-standards.md) - Complete test naming conventions guide
