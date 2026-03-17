"""Tests for service factories."""

import threading

import pytest

from appinfra.log import Logger
from appinfra.service import (
    ChannelConfig,
    ChannelFactory,
    ChannelPair,
    Message,
    ProcessChannel,
    RestartPolicy,
    RunnerFactory,
    RunnerWithChannel,
    Service,
    ServiceFactory,
    ServiceRegistration,
    ThreadChannel,
    ThreadRunner,
)

# Test fixtures


class SimpleService(Service):
    """Simple test service."""

    def __init__(self, lg: Logger) -> None:
        self._lg = lg
        self._stop = threading.Event()

    @property
    def name(self) -> str:
        return "simple"

    def execute(self) -> None:
        self._stop.wait()

    def teardown(self) -> None:
        self._stop.set()

    def is_healthy(self) -> bool:
        return True


class ConfigurableService(Service):
    """Service with extra config."""

    def __init__(self, lg: Logger, host: str = "localhost", port: int = 8080) -> None:
        self._lg = lg
        self.host = host
        self.port = port
        self._stop = threading.Event()

    @property
    def name(self) -> str:
        return "configurable"

    def execute(self) -> None:
        self._stop.wait()

    def teardown(self) -> None:
        self._stop.set()

    def is_healthy(self) -> bool:
        return True


@pytest.fixture
def lg() -> Logger:
    """Create a test logger."""
    return Logger(name="test")


# ChannelFactory tests


class TestChannelConfig:
    """Tests for ChannelConfig."""

    def test_defaults(self) -> None:
        """Default values are sensible."""
        cfg = ChannelConfig()
        assert cfg.response_timeout == 30.0
        assert cfg.max_queue_size == 0

    def test_custom_values(self) -> None:
        """Custom values are preserved."""
        cfg = ChannelConfig(response_timeout=60.0, max_queue_size=100)
        assert cfg.response_timeout == 60.0
        assert cfg.max_queue_size == 100


class TestChannelFactory:
    """Tests for ChannelFactory."""

    def test_create_thread_pair(self) -> None:
        """Creates connected ThreadChannel pair."""
        factory = ChannelFactory()
        pair = factory.create_thread_pair()

        assert isinstance(pair, ChannelPair)
        assert isinstance(pair.parent, ThreadChannel)
        assert isinstance(pair.child, ThreadChannel)

        # Verify connectivity
        pair.parent.send(Message(payload="test"))
        msg = pair.child.recv(timeout=0.1)
        assert msg.payload == "test"

    def test_create_thread_pair_with_config(self) -> None:
        """Thread pair respects configuration."""
        config = ChannelConfig(response_timeout=5.0)
        factory = ChannelFactory(config)
        pair = factory.create_thread_pair()

        # Response timeout is configured
        assert pair.parent._response_timeout == 5.0

    def test_create_process_pair(self) -> None:
        """Creates connected ProcessChannel pair."""
        factory = ChannelFactory()
        pair = factory.create_process_pair()

        assert isinstance(pair, ChannelPair)
        assert isinstance(pair.parent, ProcessChannel)
        assert isinstance(pair.child, ProcessChannel)

        # Verify connectivity
        pair.parent.send(Message(payload="test"))
        msg = pair.child.recv(timeout=0.1)
        assert msg.payload == "test"

        pair.close()

    def test_channel_pair_close(self) -> None:
        """ChannelPair.close() closes both channels."""
        factory = ChannelFactory()
        pair = factory.create_thread_pair()

        pair.close()

        assert pair.parent.is_closed
        assert pair.child.is_closed

    def test_create_thread_pair_with_max_queue_size(self) -> None:
        """Thread pair respects max queue size."""
        config = ChannelConfig(max_queue_size=2)
        factory = ChannelFactory(config)
        pair = factory.create_thread_pair()

        assert pair.parent is not None
        assert pair.child is not None

        # Verify max queue size is enforced
        pair.parent.send(Message(payload="msg1"))
        pair.parent.send(Message(payload="msg2"))
        # Queue should be full now - verify by checking underlying queue
        assert pair.child._inbound.full()  # type: ignore[union-attr]

        pair.close()

    def test_create_process_pair_with_max_queue_size(self) -> None:
        """Process pair respects max queue size."""
        config = ChannelConfig(max_queue_size=10)
        factory = ChannelFactory(config)
        pair = factory.create_process_pair()

        assert pair.parent is not None
        assert pair.child is not None
        pair.close()


# RunnerFactory tests


class TestRunnerFactory:
    """Tests for RunnerFactory."""

    def test_create_thread_runner(self, lg: Logger) -> None:
        """Creates ThreadRunner for service."""
        factory = RunnerFactory(lg)
        service = SimpleService(lg)

        runner = factory.create_thread_runner(service)

        assert isinstance(runner, ThreadRunner)
        assert runner.service is service

    def test_create_thread_runner_with_policy(self, lg: Logger) -> None:
        """Applies restart policy to runner."""
        policy = RestartPolicy(max_retries=5)
        factory = RunnerFactory(lg, default_policy=policy)
        service = SimpleService(lg)

        runner = factory.create_thread_runner(service)

        assert runner.policy is policy

    def test_create_thread_runner_override_policy(self, lg: Logger) -> None:
        """Per-runner policy overrides default."""
        default_policy = RestartPolicy(max_retries=3)
        override_policy = RestartPolicy(max_retries=10)
        factory = RunnerFactory(lg, default_policy=default_policy)
        service = SimpleService(lg)

        runner = factory.create_thread_runner(service, policy=override_policy)

        assert runner.policy is override_policy

    def test_create_thread_runner_with_channel(self, lg: Logger) -> None:
        """Creates runner with channel pair."""
        factory = RunnerFactory(lg)
        service = SimpleService(lg)

        result = factory.create_thread_runner_with_channel(service)

        assert isinstance(result, RunnerWithChannel)
        assert isinstance(result.runner, ThreadRunner)
        assert isinstance(result.channel, ThreadChannel)
        assert isinstance(result.service_channel, ThreadChannel)

        # Verify channels are connected
        result.channel.send(Message(payload="ping"))
        msg = result.service_channel.recv(timeout=0.1)
        assert msg.payload == "ping"

    def test_create_process_runner(self, lg: Logger) -> None:
        """Creates ProcessRunner for service."""
        from appinfra.service import ProcessRunner

        factory = RunnerFactory(lg)
        service = SimpleService(lg)

        runner = factory.create_process_runner(service)

        assert isinstance(runner, ProcessRunner)
        assert runner.service is service

    def test_create_process_runner_with_channel(self, lg: Logger) -> None:
        """Creates ProcessRunner with channel pair."""
        from appinfra.service import ProcessChannel, ProcessRunner

        factory = RunnerFactory(lg)
        service = SimpleService(lg)

        result = factory.create_process_runner_with_channel(service)

        try:
            assert isinstance(result, RunnerWithChannel)
            assert isinstance(result.runner, ProcessRunner)
            assert isinstance(result.channel, ProcessChannel)
            assert isinstance(result.service_channel, ProcessChannel)

            # Verify channels are connected
            result.channel.send(Message(payload="test"))
            msg = result.service_channel.recv(timeout=0.5)
            assert msg.payload == "test"
        finally:
            # Ensure both channels are closed to prevent resource leak
            result.channel.close()
            result.service_channel.close()


# ServiceFactory tests


class TestServiceFactory:
    """Tests for ServiceFactory."""

    def test_register_and_create(self, lg: Logger) -> None:
        """Register service type and create instance."""
        factory = ServiceFactory(lg)
        factory.register("simple", SimpleService)

        service = factory.create("simple")

        assert isinstance(service, SimpleService)
        assert service.name == "simple"

    def test_register_duplicate_raises(self, lg: Logger) -> None:
        """Registering same name twice raises."""
        factory = ServiceFactory(lg)
        factory.register("simple", SimpleService)

        with pytest.raises(ValueError, match="already registered"):
            factory.register("simple", SimpleService)

    def test_create_unknown_raises(self, lg: Logger) -> None:
        """Creating unknown service raises."""
        factory = ServiceFactory(lg)

        with pytest.raises(KeyError, match="not registered"):
            factory.create("unknown")

    def test_create_with_kwargs(self, lg: Logger) -> None:
        """Passes kwargs to service constructor."""
        factory = ServiceFactory(lg)
        factory.register("configurable", ConfigurableService)

        service = factory.create("configurable", host="example.com", port=9000)

        assert isinstance(service, ConfigurableService)
        assert service.host == "example.com"
        assert service.port == 9000

    def test_register_with_default_kwargs(self, lg: Logger) -> None:
        """Registered kwargs are used as defaults."""
        factory = ServiceFactory(lg)
        factory.register("configurable", ConfigurableService, host="default.com")

        service = factory.create("configurable")

        assert service.host == "default.com"
        assert service.port == 8080  # class default

    def test_create_kwargs_override_registered(self, lg: Logger) -> None:
        """Create-time kwargs override registered defaults."""
        factory = ServiceFactory(lg)
        factory.register("configurable", ConfigurableService, host="default.com")

        service = factory.create("configurable", host="override.com")

        assert service.host == "override.com"

    def test_register_with_factory_fn(self, lg: Logger) -> None:
        """Uses factory function for custom creation."""

        def custom_factory(lg: Logger, **kwargs: object) -> SimpleService:
            svc = SimpleService(lg)
            svc.custom_attr = "injected"  # type: ignore
            return svc

        factory = ServiceFactory(lg)
        factory.register("custom", SimpleService, factory_fn=custom_factory)

        service = factory.create("custom")

        assert hasattr(service, "custom_attr")
        assert service.custom_attr == "injected"  # type: ignore

    def test_register_with_policy(self, lg: Logger) -> None:
        """Stores restart policy with registration."""
        policy = RestartPolicy(max_retries=5)
        factory = ServiceFactory(lg)
        factory.register("simple", SimpleService, policy=policy)

        assert factory.get_policy("simple") is policy

    def test_register_with_channel(self, lg: Logger) -> None:
        """Tracks channel requirement."""
        factory = ServiceFactory(lg)
        factory.register("worker", SimpleService, with_channel=True)

        assert factory.needs_channel("worker") is True

    def test_unregister(self, lg: Logger) -> None:
        """Removes registration."""
        factory = ServiceFactory(lg)
        factory.register("simple", SimpleService)
        factory.unregister("simple")

        assert not factory.is_registered("simple")

    def test_unregister_unknown_raises(self, lg: Logger) -> None:
        """Unregistering unknown name raises."""
        factory = ServiceFactory(lg)

        with pytest.raises(KeyError, match="not registered"):
            factory.unregister("unknown")

    def test_registered_names(self, lg: Logger) -> None:
        """Lists registered service names."""
        factory = ServiceFactory(lg)
        factory.register("svc1", SimpleService)
        factory.register("svc2", ConfigurableService)

        names = factory.registered_names

        assert set(names) == {"svc1", "svc2"}

    def test_get_registration(self, lg: Logger) -> None:
        """Returns full registration info."""
        policy = RestartPolicy(max_retries=3)
        factory = ServiceFactory(lg)
        factory.register(
            "worker",
            SimpleService,
            with_channel=True,
            policy=policy,
            extra_kwarg="value",
        )

        reg = factory.get_registration("worker")

        assert isinstance(reg, ServiceRegistration)
        assert reg.service_cls is SimpleService
        assert reg.with_channel is True
        assert reg.policy is policy
        assert reg.kwargs == {"extra_kwarg": "value"}
