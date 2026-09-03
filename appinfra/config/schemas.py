# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Configuration schemas using Pydantic for validation.

This module is optional - it's only used if pydantic is installed.
Users can install it with: pip install infra[validation]
"""

try:
    import re
    from typing import Any, Self

    from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

    PYDANTIC_AVAILABLE = True

    class HandlerConfig(BaseModel):
        """Configuration for a logging handler."""

        type: str = Field(
            ..., description="Handler type (console, file, json, database)"
        )
        level: str | None = Field(None, description="Log level for this handler")
        location: bool | int | None = Field(
            None, description="Show file locations in logs"
        )
        micros: bool | None = Field(None, description="Show microsecond timestamps")
        # File handler specific
        filename: str | None = None
        maxBytes: int | None = None
        backupCount: int | None = None
        # Database handler specific
        table: str | None = None
        buffer_size: int | None = None
        flush_interval: float | None = None
        flush_level: str | None = None

        model_config = ConfigDict(extra="allow")  # Allow additional fields

    class LoggingConfig(BaseModel):
        """Configuration for logging."""

        level: str = Field(default="info", description="Global log level")
        location: bool | int = Field(
            default=False, description="Show file locations in logs"
        )
        micros: bool = Field(default=False, description="Show microsecond timestamps")
        handlers: dict[str, HandlerConfig] | None = Field(
            default=None, description="Handler configurations"
        )

        @field_validator("level")
        @classmethod
        def validate_log_level(cls, v: Any) -> Any:
            """Validate log level is a recognized level."""
            valid_levels = [
                "TRACE2",
                "TRACE",
                "DEBUG",
                "INFO",
                "WARNING",
                "ERROR",
                "CRITICAL",
            ]
            if isinstance(v, str) and v.upper() not in valid_levels:
                raise ValueError(
                    f"Invalid log level '{v}'. Must be one of: {', '.join(valid_levels)}"
                )
            return v

        model_config = ConfigDict(extra="allow")

    class PostgreSQLServerConfig(BaseModel):
        """Configuration for PostgreSQL server connection."""

        version: int | None = Field(
            default=None,
            description="PostgreSQL version. Required unless image is specified",
        )
        name: str = Field(default="llm-works-pg", description="Server name")
        port: int = Field(default=25432, ge=1, le=65535, description="Server port")
        user: str = Field(default="postgres", description="Username")
        password: str = Field(default="", alias="pass", description="Password")
        image: str | None = Field(
            default=None,
            description="Docker image (e.g., pgvector/pgvector:pg18). Defaults to postgres:VERSION",
        )
        postgres_conf: dict[str, str | int | bool | list[str]] = Field(
            default_factory=dict,
            description="PostgreSQL config parameters passed as -c key=value (lists joined with commas)",
        )

        @model_validator(mode="after")
        def validate_version_or_image(self) -> Self:
            """Ensure either version or image is specified."""
            if self.version is None and self.image is None:
                raise ValueError("Either 'version' or 'image' must be specified")
            return self

        model_config = ConfigDict(
            populate_by_name=True,  # Allow both 'password' and 'pass'
            extra="allow",
        )

    class DatabaseConfig(BaseModel):
        """Configuration for a database connection."""

        url: str = Field(..., description="Database connection URL")
        pool_size: int = Field(default=5, ge=1, description="Connection pool size")
        max_overflow: int = Field(
            default=10, ge=0, description="Max overflow connections"
        )
        pool_timeout: int = Field(default=30, ge=1, description="Pool timeout seconds")
        pool_recycle: int = Field(
            default=3600, ge=-1, description="Pool recycle seconds"
        )
        pool_pre_ping: bool = Field(
            default=True, description="Enable connection health checks"
        )
        readonly: bool = Field(default=False, description="Read-only mode")
        create_db: bool = Field(
            default=False, description="Create database if not exists"
        )
        # Auto-reconnect settings
        auto_reconnect: bool = Field(
            default=True, description="Enable automatic reconnection"
        )
        max_retries: int = Field(
            default=3, ge=0, description="Max reconnection retries"
        )
        retry_delay: float = Field(
            default=1.0, ge=0.0, description="Initial retry delay in seconds"
        )
        extensions: list[str] = Field(
            default_factory=list,
            description="PostgreSQL extensions to create (e.g., ['vector', 'postgis'])",
        )
        isolation_schema: str | None = Field(
            default=None,
            alias="schema",
            description="PostgreSQL schema for isolation (e.g., 'test_gw0')",
        )

        @field_validator("url")
        @classmethod
        def validate_url(cls, v: Any) -> Any:
            """Validate database URL format."""
            if not v.startswith(("postgresql://", "postgres://")):
                raise ValueError(
                    "Database URL must start with 'postgresql://' or 'postgres://'"
                )
            return v

        @field_validator("extensions")
        @classmethod
        def validate_extensions(cls, v: list[str]) -> list[str]:
            """Validate extension names are safe SQL identifiers."""
            pattern = re.compile(r"^[a-z][a-z0-9_-]*$")
            for ext in v:
                if not pattern.match(ext):
                    raise ValueError(
                        f"Invalid extension name '{ext}'. Must start with lowercase "
                        "letter and contain only lowercase letters, numbers, "
                        "underscores, and hyphens."
                    )
            return v

        @field_validator("isolation_schema")
        @classmethod
        def validate_isolation_schema(cls, v: str | None) -> str | None:
            """Validate schema name is a safe SQL identifier."""
            if v is None:
                return v
            pattern = re.compile(r"^[a-z][a-z0-9_]*$")
            if not pattern.match(v):
                raise ValueError(
                    f"Invalid schema name '{v}'. Must start with lowercase letter "
                    "and contain only lowercase letters, numbers, and underscores."
                )
            return v

        model_config = ConfigDict(extra="allow")

    class TestConfig(BaseModel):
        """Configuration for testing."""

        cleanup: bool = Field(default=True, description="Cleanup test data")
        create_test_tables: bool = Field(default=True, description="Create test tables")
        logging: LoggingConfig | None = Field(
            default=None, description="Test-specific logging config"
        )

        model_config = ConfigDict(extra="allow")

    class InfraConfig(BaseModel):
        """
        Complete infrastructure configuration schema.

        This validates the structure of infra.yaml configuration files.
        """

        logging: LoggingConfig = Field(
            default_factory=LoggingConfig, description="Logging configuration"
        )
        pgserver: PostgreSQLServerConfig | None = Field(
            default=None, description="PostgreSQL server config"
        )
        dbs: dict[str, DatabaseConfig] = Field(
            default_factory=dict, description="Database configurations"
        )
        test: TestConfig | None = Field(default=None, description="Test configuration")

        model_config = ConfigDict(
            extra="allow"
        )  # Allow additional application-specific sections

    def validate_config(config_dict: dict[str, Any]) -> InfraConfig:
        """
        Validate a configuration dictionary against the schema.

        Args:
            config_dict: Dictionary containing configuration data

        Returns:
            Validated InfraConfig instance

        Raises:
            ValidationError: If configuration is invalid

        Example:
            import logging
            from . import validate_config

            lg = logging.getLogger(__name__)
            config_data = {...}
            try:
                validated = validate_config(config_data)
                lg.info("config is valid!")
            except ValidationError as e:
                lg.error(f"Invalid config: {e}")
        """
        return InfraConfig(**config_dict)

except ImportError:
    # Pydantic not installed
    PYDANTIC_AVAILABLE = False

    # Provide dummy classes that pass through
    class InfraConfig:  # type: ignore[no-redef]
        """Dummy config class when pydantic not available."""

        pass

    class LoggingConfig:  # type: ignore[no-redef]
        """Dummy logging config class."""

        pass

    class DatabaseConfig:  # type: ignore[no-redef]
        """Dummy database config class."""

        pass

    def validate_config(config_dict: dict[str, Any]) -> dict[str, Any]:  # type: ignore[no-redef,misc]
        """No-op validation when pydantic not installed."""
        return config_dict
