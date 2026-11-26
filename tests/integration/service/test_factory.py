# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for channel factories whose queues cross processes."""

from appinfra.service import (
    Channel,
    ChannelPair,
    Message,
    ProcessQueueChannelFactory,
)


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
