# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Topic-based logging level manager with glob pattern matching.

This module provides the LogLevelManager singleton for managing logger levels
based on topic patterns (e.g., '/infra/db/*', '/infra/**'). It supports:
- Glob pattern matching with * (single segment) and ** (recursive)
- Rule precedence (API > CLI > YAML)
- Pattern specificity resolution
- Optional runtime updates to existing loggers
- Thread-safe operation
"""

from __future__ import annotations

import fnmatch
import logging
import threading
from dataclasses import dataclass


@dataclass
class LevelRule:
    """
    Single level rule for a topic pattern.

    Attributes:
        pattern: Glob pattern (e.g., "/infra/db/*")
        level: Log level (int or string)
        source: Rule source ("yaml", "cli", "api", "runtime")
        priority: Rule priority (higher wins)
        specificity: Pattern specificity score (higher is more specific)
    """

    pattern: str
    level: int | str
    source: str
    priority: int
    specificity: int


class LogLevelManager:
    """
    Thread-safe singleton for topic-based logging level management.

    Manages glob pattern-based rules for logger levels with support for:
    - Multiple configuration sources (YAML, CLI, API)
    - Priority-based rule precedence
    - Pattern specificity resolution
    - Optional runtime updates to existing loggers

    Example:
        >>> manager = LogLevelManager.get_instance()
        >>> manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)
        >>> manager.get_effective_level("/infra/db/queries")  # Returns DEBUG
    """

    _instance: LogLevelManager | None = None
    _lock_class = threading.Lock()  # Class-level lock for singleton

    def __init__(self) -> None:
        """Initialize the LogLevelManager (private - use get_instance())."""
        self._rules: list[LevelRule] = []
        self._lock = threading.RLock()
        self._runtime_updates_enabled: bool = False
        self._default_level: int | str = logging.INFO

    @classmethod
    def get_instance(cls) -> LogLevelManager:
        """
        Get the singleton instance of LogLevelManager.

        Returns:
            The singleton LogLevelManager instance

        Thread-safe lazy initialization.
        """
        if cls._instance is None:
            with cls._lock_class:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """
        Reset the singleton instance (for testing only).

        Warning:
            This should only be used in test cleanup to reset state.
        """
        with cls._lock_class:
            cls._instance = None

    def add_rule(
        self, pattern: str, level: int | str, source: str, priority: int
    ) -> None:
        """
        Add a single level rule for a topic pattern.

        Args:
            pattern: Glob pattern (e.g., "/infra/db/*", "/infra/**")
            level: Log level (string or numeric)
            source: Rule source ("yaml", "cli", "api", "runtime")
            priority: Rule priority (higher wins)

        Raises:
            ValueError: If pattern is invalid

        Example:
            >>> manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)
        """
        # Validate pattern
        self._validate_pattern(pattern)

        # Calculate specificity
        specificity = self._calculate_specificity(pattern)

        with self._lock:
            # Create rule
            rule = LevelRule(pattern, level, source, priority, specificity)
            self._rules.append(rule)

            # Sort rules by priority desc, then specificity desc
            self._rules.sort(key=lambda r: (r.priority, r.specificity), reverse=True)

            # Update existing loggers if runtime updates enabled
            if self._runtime_updates_enabled:
                self._update_existing_loggers(pattern, level)

    def add_rules_from_dict(
        self, rules_dict: dict[str, str], source: str, priority: int
    ) -> None:
        """
        Add multiple rules from a dictionary.

        Args:
            rules_dict: Dictionary mapping patterns to levels
            source: Rule source ("yaml", "cli", "api")
            priority: Rule priority for all rules

        Example:
            >>> manager.add_rules_from_dict({
            ...     "/infra/db/*": "debug",
            ...     "/infra/api/*": "warning"
            ... }, source="yaml", priority=1)
        """
        for pattern, level in rules_dict.items():
            self.add_rule(pattern, level, source, priority)

    def get_effective_level(self, logger_name: str) -> int | str | None:
        """
        Get the effective log level for a logger name.

        Applies rule matching with priority and specificity resolution:
        1. Sorted by priority desc, then specificity desc
        2. First matching pattern wins
        3. If no match, returns None (use default level)

        Args:
            logger_name: Logger name to match (e.g., "/infra/db/queries")

        Returns:
            Effective log level or None if no match

        Example:
            >>> manager.add_rule("/infra/db/*", "debug", source="yaml", priority=1)
            >>> manager.get_effective_level("/infra/db/queries")
            'debug'
        """
        with self._lock:
            for rule in self._rules:  # Already sorted by priority, specificity
                if self._matches_pattern(logger_name, rule.pattern):
                    return rule.level

        # No match, will use default level
        return None

    def set_default_level(self, level: int | str) -> None:
        """
        Set the default log level (used when no pattern matches).

        Args:
            level: Default log level
        """
        with self._lock:
            self._default_level = level

    def get_default_level(self) -> int | str:
        """Get the default log level."""
        with self._lock:
            return self._default_level

    def enable_runtime_updates(self) -> None:
        """
        Enable runtime updates to existing loggers.

        When enabled, subsequent add_rule() calls will immediately update
        all matching existing loggers.

        Warning:
            Should be called before creating loggers for consistent behavior.
        """
        with self._lock:
            self._runtime_updates_enabled = True

    def disable_runtime_updates(self) -> None:
        """
        Disable runtime updates to existing loggers.

        New rules will only apply to newly created loggers.
        """
        with self._lock:
            self._runtime_updates_enabled = False

    def is_runtime_updates_enabled(self) -> bool:
        """Check if runtime updates are enabled."""
        with self._lock:
            return self._runtime_updates_enabled

    def clear_rules(self, source: str | None = None) -> None:
        """
        Clear all rules or rules from a specific source.

        Args:
            source: If specified, only clear rules from this source

        Example:
            >>> manager.clear_rules(source="api")  # Clear only API rules
            >>> manager.clear_rules()  # Clear all rules
        """
        with self._lock:
            if source is None:
                self._rules.clear()
            else:
                self._rules = [r for r in self._rules if r.source != source]

    def get_rules(self, source: str | None = None) -> list[LevelRule]:
        """
        Get all rules or rules from a specific source.

        Args:
            source: If specified, only return rules from this source

        Returns:
            List of LevelRule objects (sorted by priority/specificity)
        """
        with self._lock:
            if source is None:
                return list(self._rules)
            else:
                return [r for r in self._rules if r.source == source]

    def _matches_pattern(self, logger_name: str, pattern: str) -> bool:
        """
        Check if logger name matches a glob pattern.

        Supports:
        - * (single segment wildcard)
        - ** (recursive wildcard matching any depth)
        - Exact paths (no wildcards)

        Args:
            logger_name: Logger name to test
            pattern: Glob pattern

        Returns:
            True if logger name matches pattern

        Examples:
            >>> self._matches_pattern("/infra/db/queries", "/infra/db/*")
            True
            >>> self._matches_pattern("/infra/db/pg/queries", "/infra/db/*")
            False
            >>> self._matches_pattern("/infra/db/pg/queries", "/infra/**")
            True
        """
        # Handle recursive wildcard **
        if "**" in pattern:
            return self._matches_recursive_pattern(logger_name, pattern)

        # Handle single-segment wildcards - match segment by segment
        if "*" in pattern:
            return self._matches_single_wildcard_pattern(logger_name, pattern)

        # Exact match
        return logger_name == pattern

    def _matches_single_wildcard_pattern(self, logger_name: str, pattern: str) -> bool:
        """
        Match pattern with * wildcards (single segment only).

        Args:
            logger_name: Logger name to test
            pattern: Pattern with * wildcards

        Returns:
            True if matches
        """
        # Split into segments
        name_parts = logger_name.strip("/").split("/")
        pattern_parts = pattern.strip("/").split("/")

        # Must have same number of segments
        if len(name_parts) != len(pattern_parts):
            return False

        # Match each segment
        for name_part, pattern_part in zip(name_parts, pattern_parts):
            if not fnmatch.fnmatch(name_part, pattern_part):
                return False

        return True

    def _matches_recursive_pattern(self, logger_name: str, pattern: str) -> bool:
        """
        Match logger name against pattern containing ** (recursive wildcard).

        Args:
            logger_name: Logger name to test
            pattern: Pattern containing **

        Returns:
            True if matches
        """
        # Split pattern into prefix, **, and suffix
        parts = pattern.split("/**/")

        if len(parts) == 1:
            # Pattern ends with /** or starts with **/
            if pattern.endswith("/**"):
                prefix = pattern[:-3]
                return logger_name.startswith(prefix)
            elif pattern.startswith("**/"):
                suffix = pattern[3:]
                return logger_name.endswith(suffix)
            else:
                # No /** in pattern, shouldn't happen
                return fnmatch.fnmatch(logger_name, pattern)

        # Pattern has prefix/**/.../suffix structure
        prefix = parts[0]
        suffix = "/" + "/".join(parts[1:])

        return logger_name.startswith(prefix) and logger_name.endswith(suffix)

    def _calculate_specificity(self, pattern: str) -> int:
        """
        Calculate pattern specificity score.

        Scoring:
        - Each non-wildcard segment: +10 points
        - Each * wildcard: +1 point
        - ** wildcard: +0 points

        Args:
            pattern: Glob pattern

        Returns:
            Specificity score (higher is more specific)

        Examples:
            >>> self._calculate_specificity("/infra/db/queries")
            30  # 3 segments
            >>> self._calculate_specificity("/infra/db/*")
            21  # 2 segments + 1 wildcard
            >>> self._calculate_specificity("/infra/**")
            10  # 1 segment + recursive wildcard
        """
        # Remove leading/trailing slashes for consistent splitting
        pattern = pattern.strip("/")

        # Split into segments
        segments = pattern.split("/")

        score = 0
        for segment in segments:
            if segment == "**":
                # Recursive wildcard: 0 points
                score += 0
            elif "*" in segment:
                # Contains wildcard: +1 point
                score += 1
            else:
                # Exact segment: +10 points
                score += 10

        return score

    def _validate_pattern(self, pattern: str) -> None:
        """
        Validate that a pattern is well-formed.

        Args:
            pattern: Pattern to validate

        Raises:
            ValueError: If pattern is invalid
        """
        if not pattern:
            raise ValueError("Pattern cannot be empty")

        if not pattern.startswith("/"):
            raise ValueError(f"Pattern must start with '/': {pattern}")

        # Test pattern against a dummy name to catch syntax errors
        try:
            self._matches_pattern("/test/path", pattern)
        except Exception as e:
            raise ValueError(f"Invalid pattern '{pattern}': {e}") from e

    def _update_existing_loggers(self, pattern: str, level: int | str) -> None:
        """
        Update all existing loggers matching the pattern (when runtime updates enabled).

        Args:
            pattern: Pattern to match
            level: New log level
        """
        # Import here to avoid circular imports
        import logging as py_logging

        # Resolve level to numeric value
        if isinstance(level, str):
            numeric_level = getattr(py_logging, level.upper(), py_logging.INFO)
        else:
            numeric_level = level

        # Update all matching loggers
        for logger_name in list(py_logging.root.manager.loggerDict.keys()):
            if self._matches_pattern(logger_name, pattern):
                logger = py_logging.getLogger(logger_name)
                if hasattr(logger, "setLevel"):
                    logger.setLevel(numeric_level)

                    # Also update handlers
                    for handler in logger.handlers:
                        handler.setLevel(numeric_level)

    # -------------------------------------------------------------------------
    # Serialization for multiprocessing
    # -------------------------------------------------------------------------

    def to_dict(self) -> dict:
        """
        Serialize the LogLevelManager state to a picklable dictionary.

        Used for passing logging configuration to subprocesses.

        Returns:
            Dict containing rules and default level, suitable for from_dict()

        Example:
            config = level_manager.to_dict()
            # Pass config to subprocess...
            # In subprocess:
            LogLevelManager.get_instance().from_dict(config)
        """
        with self._lock:
            return {
                "rules": [
                    {
                        "pattern": rule.pattern,
                        "level": rule.level,
                        "source": rule.source,
                        "priority": rule.priority,
                        "specificity": rule.specificity,
                    }
                    for rule in self._rules
                ],
                "default_level": self._default_level,
            }

    def from_dict(self, config: dict) -> None:
        """
        Restore LogLevelManager state from a serialized dictionary.

        Used in subprocesses to restore the parent's logging configuration.
        This replaces any existing rules with the ones from the config.

        Args:
            config: Dict from to_dict()

        Example:
            # In subprocess:
            level_manager = LogLevelManager.get_instance()
            level_manager.from_dict(config)
        """
        with self._lock:
            # Clear existing rules and restore from config
            self._rules.clear()
            for rule_dict in config.get("rules", []):
                rule = LevelRule(
                    pattern=rule_dict["pattern"],
                    level=rule_dict["level"],
                    source=rule_dict["source"],
                    priority=rule_dict["priority"],
                    specificity=rule_dict["specificity"],
                )
                self._rules.append(rule)

            # Rules are already sorted in the serialized form, but re-sort to be safe
            self._rules.sort(key=lambda r: (r.priority, r.specificity), reverse=True)

            # Restore default level
            if "default_level" in config:
                self._default_level = config["default_level"]
