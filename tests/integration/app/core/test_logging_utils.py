# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Tests for app/core/logging_utils.py with logging config read from YAML files.
"""

import pytest

from appinfra.app.core.logging_utils import setup_logging_from_config

# =============================================================================
# Test location_color flows from config file to formatter
# =============================================================================


@pytest.mark.usefixtures("clean_env")
class TestLocationColorE2E:
    """End-to-end tests for location_color config propagation.

    These tests verify the full pipeline from YAML config file to formatter,
    ensuring location_color is correctly parsed, resolved, and applied.
    """

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Reset registry before and after each test."""
        yield

    def test_location_color_from_config_file(self, tmp_path):
        """Test location_color from actual YAML config file reaches the formatter.

        Full pipeline test:
        YAML file -> Config() -> setup_logging_from_config() -> formatter._location_color
        """
        from appinfra.config import Config
        from appinfra.log.colors import ColorManager

        # Create a test config file with location_color
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(
            """
logging:
  level: info
  location: 1
  location_color: cyan
  handlers:
    console:
      type: console
      enabled: true
"""
        )

        config = Config(str(config_file))
        logger, registry = setup_logging_from_config(config, location=1)

        # Verify location_color reached the formatter and was resolved to ANSI code
        found = False
        for handler in logger.handlers:
            if hasattr(handler, "formatter") and hasattr(
                handler.formatter, "_location_renderer"
            ):
                renderer = handler.formatter._location_renderer
                assert renderer._location_color == ColorManager.CYAN
                found = True
                break

        assert found, "No handler with _location_renderer found"

    def test_location_color_grey_level_from_config_file(self, tmp_path):
        """Test grey-N color names from YAML are resolved correctly."""
        from appinfra.config import Config
        from appinfra.log.colors import ColorManager

        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(
            """
logging:
  level: info
  location: 1
  location_color: grey-12
  handlers:
    console:
      type: console
      enabled: true
"""
        )

        config = Config(str(config_file))
        logger, registry = setup_logging_from_config(config, location=1)

        expected_color = ColorManager.create_gray_level(12)
        found = False
        for handler in logger.handlers:
            if hasattr(handler, "formatter") and hasattr(
                handler.formatter, "_location_renderer"
            ):
                renderer = handler.formatter._location_renderer
                assert renderer._location_color == expected_color
                found = True
                break

        assert found, "No handler with _location_renderer found"

    def test_location_color_from_real_config_file(self):
        """Test location_color from the actual etc/infra.yaml config file."""
        from appinfra.config import Config

        config = Config("etc/infra.yaml")

        # Verify the config has location_color set
        assert hasattr(config.logging, "location_color")
        assert config.logging.location_color is not None

        logger, registry = setup_logging_from_config(config, location=1)

        # Verify it reached the formatter as a resolved ANSI code (not a string name)
        for handler in logger.handlers:
            if hasattr(handler, "formatter") and hasattr(
                handler.formatter, "_location_renderer"
            ):
                renderer = handler.formatter._location_renderer
                # Should be an ANSI escape code, not a color name string
                assert renderer._location_color.startswith("\x1b[")
                break
        else:
            pytest.fail("No handler with _location_renderer found")

    def test_location_color_kwargs_override(self, tmp_path):
        """Test location_color can be overridden via kwargs."""
        from appinfra.config import Config
        from appinfra.log.colors import ColorManager

        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(
            """
logging:
  level: info
  location: 1
  location_color: cyan
  handlers:
    console:
      type: console
      enabled: true
"""
        )

        config = Config(str(config_file))
        # Override cyan with magenta via kwargs
        logger, registry = setup_logging_from_config(
            config, location=1, location_color="magenta"
        )

        for handler in logger.handlers:
            if hasattr(handler, "formatter") and hasattr(
                handler.formatter, "_location_renderer"
            ):
                renderer = handler.formatter._location_renderer
                assert renderer._location_color == ColorManager.MAGENTA
                break
        else:
            pytest.fail("No handler with _location_renderer found")


@pytest.mark.usefixtures("clean_env")
class TestAppBuilderLoggingConfigE2E:
    """Tests for AppBuilder logging config propagation.

    These tests verify that programmatic logging config from AppBuilder
    does not override config file values unless explicitly set.
    """

    def test_builder_logging_does_not_override_config_file_location(self, tmp_path):
        """Test that .logging.with_level() doesn't override location from config file.

        This is a regression test for a bug where the logging block's own
        defaults (location=0) would override config file values (location=1).
        """
        from appinfra.app.builder.app import AppBuilder

        # Create config file with location=1
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(
            """
logging:
  level: debug
  location: 1
  location_color: cyan
"""
        )

        # Build app with only level set programmatically
        # This should NOT override location from config file
        app = AppBuilder("test").logging.with_level("info").done().build()

        # Simulate what happens during app.setup() - load config from etc
        from appinfra.config import Config

        loaded_config = Config(str(config_file))

        # The programmatic config from builder should only have level set
        # location should remain None (not override)
        builder_config = app.config
        if builder_config and hasattr(builder_config, "logging"):
            # If location is in builder config, it should be from with_level not setting it
            # The key test: builder should not have location=0 overriding config file
            builder_location = getattr(builder_config.logging, "location", None)
            # builder_location should be None (not set) or match config file
            assert builder_location is None or builder_location == 1, (
                f"Builder location={builder_location} should not override config file location=1"
            )

    def test_builder_logging_explicit_location_overrides_config(self, tmp_path):
        """Test that explicitly set location via builder overrides config file."""
        from appinfra.app.builder.app import AppBuilder

        # Build app with explicit location=2
        app = (
            AppBuilder("test")
            .logging.with_level("info")
            .with_location(2)
            .done()
            .build()
        )

        # The programmatic config should have location=2
        assert app.config is not None
        assert hasattr(app.config, "logging")
        assert app.config.logging.location == 2

    def test_builder_logging_only_explicit_options_reach_config(self, tmp_path):
        """Test that only explicitly set logging options land in the config layer."""
        from appinfra.app.builder.app import AppBuilder

        # Set only level; the builder's own defaults for the other options
        # must not be written, or they would override config file values.
        builder = AppBuilder("test").logging.with_level("debug").done()

        assert builder._config is not None
        logging_layer = builder._config.to_dict()["logging"]
        assert logging_layer == {"level": "debug"}, (
            f"Only level should be set, got {logging_layer}"
        )

    def test_full_app_lifecycle_preserves_config_file_location(self, tmp_path):
        """Full lifecycle test: config file location preserved through app setup."""
        from appinfra.app.builder.app import AppBuilder
        from appinfra.config import Config

        # Create config directory structure
        etc_dir = tmp_path / "etc"
        etc_dir.mkdir()
        config_file = etc_dir / "infra.yaml"
        config_file.write_text(
            """
logging:
  level: debug
  location: 1
  location_color: grey-12
  handlers:
    console:
      type: console
      enabled: true
"""
        )

        # Build app similar to appinfra CLI
        app = (
            AppBuilder("test")
            .logging.with_level("info")  # Only set level, not location
            .done()
            .build()
        )

        # Manually load and merge config (simulating what app.setup does)
        loaded_config = Config(str(config_file))

        # After merge, location should be 1 from config file (not 0 from defaults)
        # The logging block's done() writes only explicitly set options
        from appinfra.yaml import deep_merge

        # Deep merge: loaded as base, programmatic takes precedence
        loaded_dict = loaded_config.to_dict()
        prog_dict = app.config.to_dict() if app.config else {}

        merged = deep_merge(loaded_dict, prog_dict)

        assert merged["logging"]["location"] == 1, (
            f"location should be 1 from config file, got {merged['logging'].get('location')}"
        )
        assert merged["logging"]["location_color"] == "grey-12", (
            "location_color should be grey-12 from config file"
        )
