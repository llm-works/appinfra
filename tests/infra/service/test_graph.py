"""Tests for service dependency graph resolution."""

import pytest

from appinfra.service import CycleError, Service
from appinfra.service.graph import dependency_levels, validate_dependencies


class MockService(Service):
    """Simple mock service for testing."""

    def __init__(self, name: str, depends_on: list[str] | None = None) -> None:
        self._name = name
        self._depends_on = depends_on or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def depends_on(self) -> list[str]:
        return self._depends_on

    def execute(self) -> None:
        pass


@pytest.mark.unit
class TestValidateDependencies:
    """Test validate_dependencies function."""

    def test_empty_services(self):
        """Empty dict is valid."""
        validate_dependencies({})

    def test_single_service_no_deps(self):
        """Single service with no dependencies is valid."""
        services = {"a": MockService("a")}
        validate_dependencies(services)

    def test_simple_chain(self):
        """Linear dependency chain is valid."""
        services = {
            "a": MockService("a"),
            "b": MockService("b", ["a"]),
            "c": MockService("c", ["b"]),
        }
        validate_dependencies(services)

    def test_diamond_dependency(self):
        """Diamond pattern (A <- B, A <- C, B <- D, C <- D) is valid."""
        services = {
            "a": MockService("a"),
            "b": MockService("b", ["a"]),
            "c": MockService("c", ["a"]),
            "d": MockService("d", ["b", "c"]),
        }
        validate_dependencies(services)

    def test_missing_dependency(self):
        """Missing dependency raises ValueError."""
        services = {"a": MockService("a", ["nonexistent"])}
        with pytest.raises(ValueError, match="unknown service 'nonexistent'"):
            validate_dependencies(services)

    def test_self_dependency(self):
        """Self-dependency is detected as cycle."""
        services = {"a": MockService("a", ["a"])}
        with pytest.raises(CycleError) as exc_info:
            validate_dependencies(services)
        assert exc_info.value.cycle == ["a"]

    def test_simple_cycle(self):
        """Simple A -> B -> A cycle is detected."""
        services = {
            "a": MockService("a", ["b"]),
            "b": MockService("b", ["a"]),
        }
        with pytest.raises(CycleError) as exc_info:
            validate_dependencies(services)
        cycle = exc_info.value.cycle
        assert set(cycle) == {"a", "b"}
        assert "Dependency cycle detected:" in str(exc_info.value)

    def test_long_cycle(self):
        """A -> B -> C -> A cycle is detected."""
        services = {
            "a": MockService("a", ["b"]),
            "b": MockService("b", ["c"]),
            "c": MockService("c", ["a"]),
        }
        with pytest.raises(CycleError) as exc_info:
            validate_dependencies(services)
        cycle = exc_info.value.cycle
        assert set(cycle) == {"a", "b", "c"}

    def test_cycle_in_subgraph(self):
        """Cycle in a subgraph is detected even with valid nodes."""
        services = {
            "root": MockService("root"),
            "a": MockService("a", ["root", "b"]),
            "b": MockService("b", ["c"]),
            "c": MockService("c", ["a"]),  # Creates cycle: a -> b -> c -> a
        }
        with pytest.raises(CycleError):
            validate_dependencies(services)


@pytest.mark.unit
class TestDependencyLevels:
    """Test dependency_levels function."""

    def test_empty_services(self):
        """Empty dict returns empty list."""
        assert dependency_levels({}) == []

    def test_single_service(self):
        """Single service is level 0."""
        services = {"a": MockService("a")}
        levels = dependency_levels(services)
        assert levels == [["a"]]

    def test_independent_services(self):
        """Independent services are all level 0."""
        services = {
            "a": MockService("a"),
            "b": MockService("b"),
            "c": MockService("c"),
        }
        levels = dependency_levels(services)
        assert len(levels) == 1
        assert set(levels[0]) == {"a", "b", "c"}

    def test_simple_chain(self):
        """Chain A <- B <- C gives 3 levels."""
        services = {
            "a": MockService("a"),
            "b": MockService("b", ["a"]),
            "c": MockService("c", ["b"]),
        }
        levels = dependency_levels(services)
        assert len(levels) == 3
        assert levels[0] == ["a"]
        assert levels[1] == ["b"]
        assert levels[2] == ["c"]

    def test_diamond_dependency(self):
        """Diamond pattern gives correct levels."""
        services = {
            "a": MockService("a"),
            "b": MockService("b", ["a"]),
            "c": MockService("c", ["a"]),
            "d": MockService("d", ["b", "c"]),
        }
        levels = dependency_levels(services)
        assert len(levels) == 3
        assert levels[0] == ["a"]
        assert set(levels[1]) == {"b", "c"}
        assert levels[2] == ["d"]

    def test_multiple_roots(self):
        """Multiple independent roots with dependents."""
        services = {
            "db": MockService("db"),
            "cache": MockService("cache"),
            "api": MockService("api", ["db", "cache"]),
        }
        levels = dependency_levels(services)
        assert len(levels) == 2
        assert set(levels[0]) == {"db", "cache"}
        assert levels[1] == ["api"]

    def test_complex_graph(self):
        """Complex graph with multiple levels and branches."""
        # Level 0: a, b
        # Level 1: c (depends on a), d (depends on b)
        # Level 2: e (depends on c, d)
        # Level 3: f (depends on e)
        services = {
            "a": MockService("a"),
            "b": MockService("b"),
            "c": MockService("c", ["a"]),
            "d": MockService("d", ["b"]),
            "e": MockService("e", ["c", "d"]),
            "f": MockService("f", ["e"]),
        }
        levels = dependency_levels(services)
        assert len(levels) == 4
        assert set(levels[0]) == {"a", "b"}
        assert set(levels[1]) == {"c", "d"}
        assert levels[2] == ["e"]
        assert levels[3] == ["f"]
