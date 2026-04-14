"""
Tests for app/builder/configurer/logging.py.

Tests key functionality including:
- LoggingConfigurer initialization
- Method chaining for logging configuration
- Config creation when None
- Integration with AppBuilder
"""

from unittest.mock import Mock

import pytest

from appinfra.app.builder.configurer.logging import LoggingConfigurer

# =============================================================================
# Test LoggingConfigurer Initialization
# =============================================================================


@pytest.mark.unit
class TestLoggingConfigurerInit:
    """Test LoggingConfigurer initialization (lines 21-28)."""

    def test_basic_initialization(self):
        """Test basic initialization stores app_builder reference."""
        app_builder = Mock()
        configurer = LoggingConfigurer(app_builder)

        assert configurer._app_builder is app_builder

    def test_initialization_with_existing_config(self):
        """Test initialization when app_builder already has config."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        assert configurer._app_builder is app_builder
        assert configurer._app_builder._logging_config is not None


# =============================================================================
# Test with_config
# =============================================================================


@pytest.mark.unit
class TestWithConfig:
    """Test with_config method (lines 30-41)."""

    def test_sets_config(self):
        """Test with_config sets the logging config (lines 40-41)."""
        app_builder = Mock()
        app_builder._logging_config = None
        config = Mock()
        configurer = LoggingConfigurer(app_builder)

        result = configurer.with_config(config)

        assert app_builder._logging_config is config

    def test_returns_self_for_chaining(self):
        """Test with_config returns self for method chaining (line 41)."""
        app_builder = Mock()
        config = Mock()
        configurer = LoggingConfigurer(app_builder)

        result = configurer.with_config(config)

        assert result is configurer

    def test_overwrites_existing_config(self):
        """Test with_config overwrites existing config."""
        app_builder = Mock()
        old_config = Mock(name="old")
        new_config = Mock(name="new")
        app_builder._logging_config = old_config
        configurer = LoggingConfigurer(app_builder)

        configurer.with_config(new_config)

        assert app_builder._logging_config is new_config


# =============================================================================
# Test with_level
# =============================================================================


@pytest.mark.unit
class TestWithLevel:
    """Test with_level method (lines 43-58)."""

    def test_sets_level_on_existing_config(self):
        """Test with_level sets level when config exists (line 57)."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        configurer.with_level("debug")

        assert app_builder._logging_config.level == "debug"

    def test_creates_config_if_none(self):
        """Test with_level creates config when None (lines 55-56)."""
        from appinfra.app.builder.app import LoggingConfig

        app_builder = Mock()
        app_builder._logging_config = None
        configurer = LoggingConfigurer(app_builder)

        configurer.with_level("warning")

        assert app_builder._logging_config is not None
        assert isinstance(app_builder._logging_config, LoggingConfig)
        assert app_builder._logging_config.level == "warning"

    def test_returns_self_for_chaining(self):
        """Test with_level returns self (line 58)."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        result = configurer.with_level("info")

        assert result is configurer

    def test_various_log_levels(self):
        """Test with_level with various log levels."""

        levels = ["debug", "info", "warning", "error", "critical"]

        for level in levels:
            app_builder = Mock()
            app_builder._logging_config = None
            configurer = LoggingConfigurer(app_builder)

            configurer.with_level(level)

            assert app_builder._logging_config.level == level


# =============================================================================
# Test with_location
# =============================================================================


@pytest.mark.unit
class TestWithLocation:
    """Test with_location method (lines 60-75)."""

    def test_sets_location_on_existing_config(self):
        """Test with_location sets depth when config exists (line 74)."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        configurer.with_location(3)

        assert app_builder._logging_config.location == 3

    def test_creates_config_if_none(self):
        """Test with_location creates config when None (lines 72-73)."""
        from appinfra.app.builder.app import LoggingConfig

        app_builder = Mock()
        app_builder._logging_config = None
        configurer = LoggingConfigurer(app_builder)

        configurer.with_location(2)

        assert app_builder._logging_config is not None
        assert isinstance(app_builder._logging_config, LoggingConfig)
        assert app_builder._logging_config.location == 2

    def test_returns_self_for_chaining(self):
        """Test with_location returns self (line 75)."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        result = configurer.with_location(1)

        assert result is configurer

    def test_zero_depth(self):
        """Test with_location with zero depth."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        configurer.with_location(0)

        assert app_builder._logging_config.location == 0


# =============================================================================
# Test with_micros
# =============================================================================


@pytest.mark.unit
class TestWithMicros:
    """Test with_micros method (lines 77-92)."""

    def test_enables_micros_on_existing_config(self):
        """Test with_micros enables microseconds (line 91)."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        configurer.with_micros(True)

        assert app_builder._logging_config.micros is True

    def test_disables_micros(self):
        """Test with_micros can disable microseconds."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        configurer.with_micros(False)

        assert app_builder._logging_config.micros is False

    def test_default_enables_micros(self):
        """Test with_micros defaults to enabled (line 77)."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        configurer.with_micros()

        assert app_builder._logging_config.micros is True

    def test_creates_config_if_none(self):
        """Test with_micros creates config when None (lines 89-90)."""
        from appinfra.app.builder.app import LoggingConfig

        app_builder = Mock()
        app_builder._logging_config = None
        configurer = LoggingConfigurer(app_builder)

        configurer.with_micros(True)

        assert app_builder._logging_config is not None
        assert isinstance(app_builder._logging_config, LoggingConfig)
        assert app_builder._logging_config.micros is True

    def test_returns_self_for_chaining(self):
        """Test with_micros returns self (line 92)."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        result = configurer.with_micros()

        assert result is configurer


# =============================================================================
# Test with_format
# =============================================================================


@pytest.mark.unit
class TestWithFormat:
    """Test with_format method (lines 94-109)."""

    def test_sets_format_on_existing_config(self):
        """Test with_format sets format string (line 108)."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        configurer.with_format("%(levelname)s - %(message)s")

        assert (
            app_builder._logging_config.format_string == "%(levelname)s - %(message)s"
        )

    def test_creates_config_if_none(self):
        """Test with_format creates config when None (lines 106-107)."""
        from appinfra.app.builder.app import LoggingConfig

        app_builder = Mock()
        app_builder._logging_config = None
        configurer = LoggingConfigurer(app_builder)

        configurer.with_format("%(name)s: %(message)s")

        assert app_builder._logging_config is not None
        assert isinstance(app_builder._logging_config, LoggingConfig)
        assert app_builder._logging_config.format_string == "%(name)s: %(message)s"

    def test_returns_self_for_chaining(self):
        """Test with_format returns self (line 109)."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        result = configurer.with_format("%(message)s")

        assert result is configurer

    def test_complex_format_string(self):
        """Test with_format handles complex format strings."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        format_str = "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s"
        configurer.with_format(format_str)

        assert app_builder._logging_config.format_string == format_str


# =============================================================================
# Test done
# =============================================================================


@pytest.mark.unit
class TestDone:
    """Test done method (lines 111-118)."""

    def test_returns_app_builder(self):
        """Test done returns parent AppBuilder (line 118)."""
        app_builder = Mock()
        configurer = LoggingConfigurer(app_builder)

        result = configurer.done()

        assert result is app_builder

    def test_done_after_configuration(self):
        """Test done after setting configuration."""
        app_builder = Mock()
        app_builder._logging_config = Mock()
        configurer = LoggingConfigurer(app_builder)

        configurer.with_level("debug")
        result = configurer.done()

        assert result is app_builder
        assert app_builder._logging_config.level == "debug"


# =============================================================================
# Test Method Chaining
# =============================================================================


@pytest.mark.unit
class TestMethodChaining:
    """Test method chaining patterns."""

    def test_full_chain_with_config(self):
        """Test complete chain with with_config."""
        app_builder = Mock()
        config = Mock()
        configurer = LoggingConfigurer(app_builder)

        result = configurer.with_config(config).done()

        assert result is app_builder
        assert app_builder._logging_config is config

    def test_full_chain_building_config(self):
        """Test complete chain building config piece by piece."""

        app_builder = Mock()
        app_builder._logging_config = None
        configurer = LoggingConfigurer(app_builder)

        result = (
            configurer.with_level("debug")
            .with_location(2)
            .with_micros(True)
            .with_format("%(message)s")
            .done()
        )

        assert result is app_builder
        assert app_builder._logging_config.level == "debug"
        assert app_builder._logging_config.location == 2
        assert app_builder._logging_config.micros is True
        assert app_builder._logging_config.format_string == "%(message)s"

    def test_partial_chain(self):
        """Test partial configuration chain."""

        app_builder = Mock()
        app_builder._logging_config = None
        configurer = LoggingConfigurer(app_builder)

        result = configurer.with_level("warning").done()

        assert result is app_builder
        # Check defaults are preserved (None means "not set, use config file value")
        config = app_builder._logging_config
        assert config.level == "warning"
        assert config.location is None  # default - will use config file value
        assert config.micros is None  # default - will use config file value

    def test_chain_order_independence(self):
        """Test that chain order doesn't matter."""

        app_builder = Mock()
        app_builder._logging_config = None
        configurer = LoggingConfigurer(app_builder)

        # Order 1: format, level, location
        configurer.with_format("fmt").with_level("error").with_location(5)

        assert app_builder._logging_config.format_string == "fmt"
        assert app_builder._logging_config.level == "error"
        assert app_builder._logging_config.location == 5


# =============================================================================
# Integration Tests
# =============================================================================


# =============================================================================
# Test with_hot_reload
# =============================================================================


@pytest.mark.unit
class TestWithHotReload:
    """Test with_hot_reload method (lines 216-284)."""

    def test_enables_hot_reload_writes_to_config(self):
        """Test with_hot_reload writes hot_reload config to _config.logging.hot_reload."""
        from appinfra.app.builder.app import ConfigFileSpec

        app_builder = Mock()
        app_builder._config = None  # Will be created by with_hot_reload
        app_builder._config_files = [
            ConfigFileSpec(path="/etc/app.yaml", from_etc_dir=False)
        ]
        configurer = LoggingConfigurer(app_builder)

        configurer.with_hot_reload(True)

        # Verify config was created and hot_reload section exists
        assert app_builder._config is not None
        assert hasattr(app_builder._config, "logging")
        assert hasattr(app_builder._config.logging, "hot_reload")
        assert app_builder._config.logging.hot_reload.enabled is True
        assert app_builder._config.logging.hot_reload.debounce_ms == 500

    def test_disables_hot_reload(self):
        """Test with_hot_reload(False) writes enabled=False to config."""
        from appinfra.app.builder.app import ConfigFileSpec
        from appinfra.dot_dict import DotDict

        app_builder = Mock()
        app_builder._config = DotDict(logging=DotDict(hot_reload=DotDict(enabled=True)))
        app_builder._config_files = [
            ConfigFileSpec(path="/etc/app.yaml", from_etc_dir=False)
        ]
        configurer = LoggingConfigurer(app_builder)

        configurer.with_hot_reload(False)

        # Verify hot_reload.enabled is False
        assert app_builder._config.logging.hot_reload.enabled is False

    def test_raises_when_no_config_files_available(self):
        """Test with_hot_reload raises when no config files available."""
        app_builder = Mock()
        app_builder._config = None
        app_builder._config_files = []  # Empty list
        configurer = LoggingConfigurer(app_builder)

        with pytest.raises(ValueError, match="with_config_file.*must be called"):
            configurer.with_hot_reload(True)

    def test_custom_debounce(self):
        """Test with_hot_reload with custom debounce."""
        from appinfra.app.builder.app import ConfigFileSpec

        app_builder = Mock()
        app_builder._config = None
        app_builder._config_files = [
            ConfigFileSpec(path="/etc/app.yaml", from_etc_dir=False)
        ]
        configurer = LoggingConfigurer(app_builder)

        configurer.with_hot_reload(True, debounce_ms=1000)

        assert app_builder._config.logging.hot_reload.debounce_ms == 1000

    def test_returns_self_for_chaining(self):
        """Test with_hot_reload returns self."""
        from appinfra.app.builder.app import ConfigFileSpec

        app_builder = Mock()
        app_builder._config = None
        app_builder._config_files = [
            ConfigFileSpec(path="/etc/app.yaml", from_etc_dir=False)
        ]
        configurer = LoggingConfigurer(app_builder)

        result = configurer.with_hot_reload(True)

        assert result is configurer


@pytest.mark.integration
class TestLoggingConfigurerIntegration:
    """Test LoggingConfigurer integration with real AppBuilder."""

    def test_with_real_logging_config(self):
        """Test integration with real LoggingConfig."""
        from appinfra.app.builder.app import LoggingConfig

        app_builder = Mock()
        app_builder._logging_config = LoggingConfig()

        configurer = LoggingConfigurer(app_builder)
        configurer.with_level("debug")
        configurer.with_location(3)
        configurer.with_micros(True)
        configurer.with_format("custom %(message)s")

        assert app_builder._logging_config.level == "debug"
        assert app_builder._logging_config.location == 3
        assert app_builder._logging_config.micros is True
        assert app_builder._logging_config.format_string == "custom %(message)s"

    def test_creates_config_with_proper_defaults(self):
        """Test that created config has proper defaults."""

        app_builder = Mock()
        app_builder._logging_config = None

        configurer = LoggingConfigurer(app_builder)
        configurer.with_level("info")

        config = app_builder._logging_config
        assert config.level == "info"
        assert config.location is None  # default - will use config file value
        assert config.micros is None  # default - will use config file value
        assert config.format_string is None
        assert config.location_color is None

    def test_full_workflow(self):
        """Test complete workflow from configurer to done."""
        from appinfra.app.builder.app import LoggingConfig

        # Simulate AppBuilder
        class FakeAppBuilder:
            def __init__(self):
                self._logging_config = None

        app_builder = FakeAppBuilder()
        configurer = LoggingConfigurer(app_builder)

        # Configure logging
        result = configurer.with_level("warning").with_location(2).with_micros().done()

        # Verify
        assert result is app_builder
        assert isinstance(app_builder._logging_config, LoggingConfig)
        assert app_builder._logging_config.level == "warning"
        assert app_builder._logging_config.location == 2
        assert app_builder._logging_config.micros is True
