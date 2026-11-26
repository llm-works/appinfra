# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for channel pairs and the factories that create them."""

import time
from typing import Any

from appinfra.service import (
    BufferedChannel,
    Channel,
    ChannelConfig,
    ChannelPair,
    ChannelPairFactory,
    ChannelTimeoutError,
    Message,
    ProcessQueueChannelFactory,
    QueueChannelFactory,
)

# Channel factory tests


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


class TestQueueChannelFactory:
    """Tests for QueueChannelFactory."""

    def test_create_pair(self) -> None:
        """Creates connected Channel pair."""
        factory = QueueChannelFactory()
        pair = factory.create_pair()

        assert isinstance(pair, ChannelPair)
        assert isinstance(pair.parent, Channel)
        assert isinstance(pair.child, Channel)

        # Verify connectivity
        pair.parent.send(Message(payload="test"))
        msg = pair.child.recv(timeout=1.0)
        assert msg.payload == "test"

    def test_create_pair_with_config(self) -> None:
        """Queue pair respects configuration."""
        config = ChannelConfig(response_timeout=5.0)
        factory = QueueChannelFactory(config)
        pair = factory.create_pair()

        # Verify config was applied (accessing private attr to avoid slow behavioral test)
        assert pair.parent._response_timeout == 5.0  # noqa: SLF001

    def test_channel_pair_close(self) -> None:
        """ChannelPair.close() closes both channels."""
        factory = QueueChannelFactory()
        pair = factory.create_pair()

        pair.close()

        assert pair.parent.is_closed
        assert pair.child.is_closed

    def test_create_pair_with_max_queue_size(self) -> None:
        """Queue pair respects max queue size."""
        config = ChannelConfig(max_queue_size=2)
        factory = QueueChannelFactory(config)
        pair = factory.create_pair()

        assert pair.parent is not None
        assert pair.child is not None

        # Verify max queue size is enforced
        pair.parent.send(Message(payload="msg1"))
        pair.parent.send(Message(payload="msg2"))
        # Queue should be full now - verify via transport's underlying queue
        assert pair.child.transport._inbound.full()  # type: ignore[union-attr]  # noqa: SLF001

        pair.close()


class TestProcessQueueChannelFactory:
    """Tests for ProcessQueueChannelFactory."""

    def test_create_pair_with_max_queue_size(self) -> None:
        """Process pair respects max queue size."""
        config = ChannelConfig(max_queue_size=10)
        factory = ProcessQueueChannelFactory(config)
        pair = factory.create_pair()

        assert pair.parent is not None
        assert pair.child is not None
        pair.close()


# Pluggable transport tests


class StubTransport:
    """Minimal Transport implementation for testing custom transports.

    Satisfies the Transport protocol with shared in-memory buffers so that
    a pair of StubTransports can exchange messages (send on one → recv on the
    other).  No base class needed — just implements send/recv/close/is_closed.
    """

    def __init__(self, inbox: list[Any], outbox: list[Any]) -> None:
        self._inbox = inbox
        self._outbox = outbox
        self._closed = False

    def send(self, message: Any, timeout: float | None = None) -> None:
        self._outbox.append(message)

    def recv(self, timeout: float | None = None) -> Any:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._inbox:
                return self._inbox.pop(0)
            if deadline is not None and time.monotonic() >= deadline:
                raise ChannelTimeoutError(f"No messages ({timeout}s)")
            time.sleep(0.01)

    def close(self) -> None:
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed


def _stub_pair() -> ChannelPair:
    """Create a connected ChannelPair backed by StubTransport."""
    parent_buf: list[Any] = []
    child_buf: list[Any] = []
    return ChannelPair(
        parent=BufferedChannel(StubTransport(inbox=parent_buf, outbox=child_buf)),
        child=BufferedChannel(StubTransport(inbox=child_buf, outbox=parent_buf)),
    )


class StubChannelFactory:
    """Custom transport factory for testing ChannelPairFactory protocol."""

    def __init__(self) -> None:
        self.calls = 0

    def create_pair(self) -> ChannelPair:
        self.calls += 1
        return _stub_pair()


class TestChannelPairFactory:
    """Tests for ChannelPairFactory protocol and pluggable transport."""

    def test_queue_channel_factory_satisfies_protocol(self) -> None:
        """Built-in QueueChannelFactory satisfies ChannelPairFactory protocol."""
        assert isinstance(QueueChannelFactory(), ChannelPairFactory)

    def test_process_queue_channel_factory_satisfies_protocol(self) -> None:
        """Built-in ProcessQueueChannelFactory satisfies ChannelPairFactory protocol."""
        assert isinstance(ProcessQueueChannelFactory(), ChannelPairFactory)

    def test_custom_factory_satisfies_protocol(self) -> None:
        """Custom factory satisfies ChannelPairFactory protocol."""
        assert isinstance(StubChannelFactory(), ChannelPairFactory)

    def test_channel_pair_accepts_custom_transport(self) -> None:
        """ChannelPair works with Channel wrapping custom Transport."""
        pair = _stub_pair()

        pair.parent.send(Message(payload="ping"))
        msg = pair.child.recv(timeout=0.1)
        assert msg.payload == "ping"

        pair.close()
        assert pair.parent.is_closed
        assert pair.child.is_closed
