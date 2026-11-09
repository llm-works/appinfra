# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for service factories whose products run on a thread."""

import pytest

from appinfra.log import Logger
from appinfra.service import (
    Channel,
    ChannelPair,
    Message,
    ProcessQueueChannelFactory,
    RunnerFactory,
    RunnerWithChannel,
)
from tests.helpers.service.factory import SimpleService


@pytest.fixture
def lg() -> Logger:
    """Create a test logger."""
    return Logger(name="test")


class TestProcessQueueChannelFactory:
    """Tests for ProcessQueueChannelFactory."""

    def test_create_pair(self) -> None:
        """Creates connected Channel pair."""
        factory = ProcessQueueChannelFactory()
        pair = factory.create_pair()

        assert isinstance(pair, ChannelPair)
        assert isinstance(pair.parent, Channel)
        assert isinstance(pair.child, Channel)

        # Verify connectivity
        pair.parent.send(Message(payload="test"))
        msg = pair.child.recv(timeout=0.1)
        assert msg.payload == "test"

        pair.close()


class TestRunnerFactory:
    """Tests for RunnerFactory."""

    def test_create_process_runner_with_channel(self, lg: Logger) -> None:
        """Creates ProcessRunner with channel pair."""
        from appinfra.service import ProcessRunner

        factory = RunnerFactory(lg)
        service = SimpleService(lg)

        result = factory.create_process_runner_with_channel(service)

        try:
            assert isinstance(result, RunnerWithChannel)
            assert isinstance(result.runner, ProcessRunner)
            assert isinstance(result.channel, Channel)
            assert isinstance(result.service_channel, Channel)

            # Verify channels are connected
            result.channel.send(Message(payload="test"))
            msg = result.service_channel.recv(timeout=0.5)
            assert msg.payload == "test"
        finally:
            # Ensure both channels are closed to prevent resource leak
            result.channel.close()
            result.service_channel.close()
