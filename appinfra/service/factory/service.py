"""Factory for service creation with dependency injection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from ...log import Logger
from ..base import Service
from ..state import RestartPolicy

T = TypeVar("T", bound=Service)


@dataclass
class ServiceRegistration:
    """Registration info for a service type.

    Attributes:
        service_cls: The service class
        factory_fn: Optional factory function (if not using class directly)
        with_channel: Whether service needs a channel
        policy: Restart policy for this service type
        kwargs: Additional kwargs to pass during creation
    """

    service_cls: type[Service]
    factory_fn: Callable[..., Service] | None = None
    with_channel: bool = False
    policy: RestartPolicy | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)


class ServiceFactory:
    """
    Registry-based factory for service creation.

    Provides dependency injection for services:
    - Register service types with their configuration
    - Create services with consistent dependencies (logger)
    - Support custom factory functions for complex initialization

    For services that need channels, use RunnerFactory which provides
    create_thread_runner_with_channel() and create_process_runner_with_channel().

    Example:
        factory = ServiceFactory(lg)

        # Register with class
        factory.register(
            "database",
            DatabaseService,
            policy=RestartPolicy(max_retries=5),
        )

        # Register with factory function
        factory.register(
            "cache",
            CacheService,
            factory_fn=lambda lg, **kw: CacheService(lg, host="localhost", **kw),
        )

        # Create instances
        db = factory.create("database")
        cache = factory.create("cache", ttl=300)

        # Check if service needs a channel (for use with RunnerFactory)
        if factory.needs_channel("worker"):
            # Use RunnerFactory.create_thread_runner_with_channel()
            pass
    """

    def __init__(self, lg: Logger) -> None:
        """
        Initialize factory.

        Args:
            lg: Logger for created services
        """
        self._lg = lg
        self._registry: dict[str, ServiceRegistration] = {}

    @property
    def registered_names(self) -> list[str]:
        """List of registered service names."""
        return list(self._registry.keys())

    def register(
        self,
        name: str,
        service_cls: type[Service],
        factory_fn: Callable[..., Service] | None = None,
        with_channel: bool = False,
        policy: RestartPolicy | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Register a service type.

        Args:
            name: Unique name for this service type
            service_cls: The service class
            factory_fn: Optional factory function for custom creation.
                       Signature: fn(lg: Logger, **kwargs) -> Service
            with_channel: Whether this service needs a channel
            policy: Default restart policy
            **kwargs: Additional kwargs stored and passed during creation

        Raises:
            ValueError: If name is already registered
        """
        if name in self._registry:
            raise ValueError(f"Service '{name}' is already registered")

        self._registry[name] = ServiceRegistration(
            service_cls=service_cls,
            factory_fn=factory_fn,
            with_channel=with_channel,
            policy=policy,
            kwargs=kwargs,
        )

    def unregister(self, name: str) -> None:
        """
        Remove a service registration.

        Args:
            name: Service name to unregister

        Raises:
            KeyError: If name is not registered
        """
        if name not in self._registry:
            raise KeyError(f"Service '{name}' is not registered")
        del self._registry[name]

    def is_registered(self, name: str) -> bool:
        """Check if a service name is registered."""
        return name in self._registry

    def get_registration(self, name: str) -> ServiceRegistration:
        """
        Get registration info for a service.

        Args:
            name: Service name

        Returns:
            ServiceRegistration with configuration

        Raises:
            KeyError: If name is not registered
        """
        if name not in self._registry:
            raise KeyError(f"Service '{name}' is not registered")
        return self._registry[name]

    def create(self, name: str, **kwargs: Any) -> Service:
        """
        Create a service instance.

        Args:
            name: Registered service name
            **kwargs: Additional kwargs (merged with registered kwargs)

        Returns:
            Service instance

        Raises:
            KeyError: If name is not registered
        """
        reg = self.get_registration(name)

        # Merge registered kwargs with call-time kwargs
        merged_kwargs = {**reg.kwargs, **kwargs}

        if reg.factory_fn is not None:
            return reg.factory_fn(self._lg, **merged_kwargs)

        return reg.service_cls(self._lg, **merged_kwargs)  # type: ignore[call-arg]

    def get_policy(self, name: str) -> RestartPolicy | None:
        """
        Get the restart policy for a service.

        Args:
            name: Service name

        Returns:
            RestartPolicy or None

        Raises:
            KeyError: If name is not registered
        """
        return self.get_registration(name).policy

    def needs_channel(self, name: str) -> bool:
        """
        Check if a service needs a channel.

        Args:
            name: Service name

        Returns:
            True if service was registered with with_channel=True

        Raises:
            KeyError: If name is not registered
        """
        return self.get_registration(name).with_channel
