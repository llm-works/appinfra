# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""ProcessRunner drives step and scheduled services in the subprocess."""

import multiprocessing as mp
from multiprocessing.synchronize import Event as MPEvent

import pytest

from appinfra.log import Logger
from appinfra.service import (
    Message,
    ProcessRunner,
    RunnerFactory,
    ScheduledService,
    State,
    StepService,
)
from tests.helpers.fork import forks_in_xdist_worker


class ProcessDoubler(StepService):
    """Replies with the payload doubled. Module-level: pickled to the subprocess."""

    def __init__(self, lg: Logger) -> None:
        self._lg = lg

    @property
    def name(self) -> str:
        return "doubler"

    def step(self, msg: Message) -> Message:
        return Message(id=msg.id, payload=msg.payload * 2)


class ProcessTicker(ScheduledService):
    """Sets *ticked* on its first tick and *torn_down* in teardown(). It does not
    watch for shutdown: the runner ends its loop."""

    interval = 0.05

    def __init__(self, lg: Logger, ticked: MPEvent, torn_down: MPEvent) -> None:
        self._lg = lg
        self._ticked = ticked
        self._torn_down = torn_down

    @property
    def name(self) -> str:
        return "ticker"

    def tick(self) -> None:
        self._ticked.set()

    def teardown(self) -> None:
        self._torn_down.set()


@forks_in_xdist_worker
class TestProcessServiceForms:
    @pytest.fixture
    def lg(self) -> Logger:
        return Logger(name="test")

    @pytest.mark.parametrize("start_method", mp.get_all_start_methods())
    def test_step_service_replies_from_the_subprocess(self, lg, start_method):
        """Under spawn and forkserver the inbox is pickled into the subprocess."""
        factory = RunnerFactory(lg, start_method=start_method)
        result = factory.create_process_runner_with_channel(ProcessDoubler(lg))
        result.runner.start()
        try:
            result.runner.wait_healthy(timeout=10.0)
            reply = result.channel.submit(Message(payload=21), timeout=10.0)
        finally:
            result.runner.stop()

        assert reply.payload == 42
        assert result.runner.state == State.STOPPED

    def test_scheduled_service_ticks_and_stops_in_the_subprocess(self, lg):
        """The runner ticks the service and ends its loop on stop().

        teardown() runs in the subprocess only after the loop returns: a process
        that stop() had to terminate never reaches it.
        """
        ctx = mp.get_context()
        ticked, torn_down = ctx.Event(), ctx.Event()
        runner = ProcessRunner(ProcessTicker(lg, ticked, torn_down))
        runner.start()
        try:
            runner.wait_healthy(timeout=10.0)
            assert ticked.wait(timeout=10.0)
        finally:
            runner.stop()

        assert runner.state == State.STOPPED
        assert torn_down.is_set()
