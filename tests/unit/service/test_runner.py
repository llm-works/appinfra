# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for the Runner record: its state machine, hooks and restart policy."""

from unittest.mock import MagicMock

import pytest

from appinfra.service import InvalidTransitionError, RestartPolicy, Runner, State
from tests.helpers.service.runner import SimpleService


class TestRunner:
    """The Runner record: its state machine, hooks and restart policy."""

    def test_a_move_transitions_allow_is_made(self):
        runner = Runner(SimpleService())
        assert runner._move(State.INITD) == State.CREATED  # Private: the Runtime's
        assert runner.state == State.INITD

    def test_a_move_transitions_forbid_raises(self):
        runner = Runner(SimpleService())
        with pytest.raises(InvalidTransitionError):
            runner._move(State.RUNNING)
        assert runner.state == State.CREATED

    def test_hooks_see_each_move_and_a_failing_one_is_logged(self):
        svc = SimpleService()
        svc._lg = MagicMock()
        runner = Runner(svc)
        seen: list[tuple[State, State]] = []

        def fails(_name: str, _old: State, _new: State) -> None:
            raise RuntimeError("hook fails")

        runner.on_state_change(fails)
        runner.on_state_change(lambda _n, old, new: seen.append((old, new)))
        runner._move(State.INITD)

        assert seen == [(State.CREATED, State.INITD)]
        svc._lg.warning.assert_called_once()

    def test_what_is_not_a_service_is_refused(self):
        with pytest.raises(TypeError, match="must be a Service"):
            Runner(object())

    def test_restart_delay_grows_with_retries_up_to_its_cap(self):
        policy = RestartPolicy(backoff=1.0, backoff_multiplier=2.0, max_backoff=5.0)
        runner = Runner(SimpleService(), policy)
        delays = []
        for retries in range(4):
            runner._retries = retries  # Private: the Runtime counts them
            delays.append(runner.restart_delay)
        assert delays == [1.0, 2.0, 4.0, 5.0]

    def test_can_restart(self):
        """can_restart holds until max_retries is reached, and never when disabled."""
        runner = Runner(SimpleService(), RestartPolicy(max_retries=2))
        assert runner.can_restart
        runner._retries = 2
        assert not runner.can_restart

        disabled = RestartPolicy(restart_on_failure=False)
        assert not Runner(SimpleService(), disabled).can_restart
