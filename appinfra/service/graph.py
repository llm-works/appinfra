"""Dependency graph resolution for services."""

from __future__ import annotations

import graphlib
from typing import TYPE_CHECKING

from .errors import CycleError

if TYPE_CHECKING:
    from .base import Service


def _build_graph(services: dict[str, Service]) -> dict[str, set[str]]:
    """Build graph dict for TopologicalSorter."""
    return {name: set(svc.depends_on) for name, svc in services.items()}


def validate_dependencies(services: dict[str, Service]) -> None:
    """Validate that all dependencies exist and there are no cycles.

    Args:
        services: Dict mapping service name to Service instance.

    Raises:
        CycleError: If a dependency cycle is detected.
        ValueError: If a dependency references a non-existent service.
    """
    # Check all dependencies exist
    for name, svc in services.items():
        for dep in svc.depends_on:
            if dep not in services:
                msg = f"Service '{name}' depends on unknown service '{dep}'"
                raise ValueError(msg)

    # Detect cycles
    try:
        ts = graphlib.TopologicalSorter(_build_graph(services))
        ts.prepare()
    except graphlib.CycleError as e:
        # e.args[1] is the cycle tuple, includes closing edge (a -> b -> a)
        # Normalize to just the cycle nodes (a -> b)
        cycle = list(e.args[1])
        if len(cycle) > 1 and cycle[0] == cycle[-1]:
            cycle = cycle[:-1]
        raise CycleError(cycle) from None


def dependency_levels(services: dict[str, Service]) -> list[list[str]]:
    """Group services into levels for parallel execution.

    Level 0 contains services with no dependencies.
    Level N contains services whose dependencies are all in levels < N.

    Services within the same level can be started/stopped in parallel.

    Args:
        services: Dict mapping service name to Service instance.

    Returns:
        List of levels, where each level is a list of service names.
        Services are ordered so dependencies come before dependents.

    Example:
        Given: A depends on B, C depends on B, D depends on A and C
        Returns: [[B], [A, C], [D]]
    """
    if not services:
        return []

    ts = graphlib.TopologicalSorter(_build_graph(services))
    ts.prepare()

    levels: list[list[str]] = []
    while ts.is_active():
        ready = list(ts.get_ready())
        levels.append(ready)
        ts.done(*ready)

    return levels
