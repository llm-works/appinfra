# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for StopToken."""

import pickle
import sys
import threading

import pytest

from appinfra.runtime import StopToken


class TestStopToken:
    def test_a_new_token_is_not_stopped(self):
        token = StopToken()
        assert not token.is_set()
        assert not token.wait(timeout=0)

    def test_stop_sets_it_for_good(self):
        token = StopToken()
        token.stop()
        token.stop()  # idempotent
        assert token.is_set()
        assert token.wait(timeout=0)

    def test_stop_reaches_a_waiter_created_before_it(self):
        """The wait event exists before stop(); stop() must set it."""
        token = StopToken()
        assert not token.wait(timeout=0)  # creates the event
        token.stop()
        assert token.wait(timeout=0)

    def test_stopping_a_parent_stops_every_descendant(self):
        root = StopToken()
        child = root.child()
        grandchild = child.child()
        root.stop()
        assert child.is_set()
        assert grandchild.is_set()

    def test_stop_reaches_the_end_of_a_chain_deeper_than_the_recursion_limit(self):
        """Depth costs no stack: a partial stop would leave the rest of the
        tree running for good, since the stopped part ignores a second stop()."""
        root = token = StopToken()
        for _ in range(sys.getrecursionlimit() + 100):
            token = token.child()
        root.stop()
        assert token.is_set()

    def test_stopping_a_child_leaves_its_parent_running(self):
        root = StopToken()
        child = root.child()
        sibling = root.child()
        child.stop()
        assert not root.is_set()
        assert not sibling.is_set()

    def test_a_child_of_a_stopped_token_starts_stopped(self):
        root = StopToken()
        root.stop()
        assert root.child().is_set()

    def test_a_detached_child_is_not_stopped_with_its_old_parent(self):
        """A run that has ended leaves the tree; its parent no longer holds it."""
        root = StopToken()
        child = root.child()
        child.detach()
        root.stop()
        assert not child.is_set()
        assert not root._children  # Private: the parent dropped its reference

    def test_a_pickled_child_stays_linked_to_its_pickled_parent(self):
        """A service sent to a subprocess keeps the tokens its setup() derived
        tied to its own: stopping the unpickled parent stops the child."""
        root = StopToken()
        child = root.child()
        root2, child2 = pickle.loads(pickle.dumps((root, child)))
        assert not child2.is_set()
        root2.stop()
        assert child2.is_set()

    def test_a_pickled_token_carries_its_ancestors_not_its_siblings(self):
        """Pickling keeps the chain to the root and no other part of the tree;
        the copies are new tokens, not stopped with the originals."""
        root = StopToken()
        child = root.child()
        root.child()  # a sibling, left behind
        child2 = pickle.loads(pickle.dumps(child))
        assert child2._parent is not None  # Private: the link to the parent
        assert child2._parent._children == {child2}
        root.stop()
        assert not child2.is_set()


class TestOnStop:
    def test_stop_calls_it_once(self):
        token = StopToken()
        calls = []
        token.on_stop(lambda: calls.append(1))
        assert calls == []
        token.stop()
        token.stop()
        assert calls == [1]

    def test_on_a_stopped_token_it_is_called_at_once(self):
        token = StopToken()
        token.stop()
        calls = []
        remove = token.on_stop(lambda: calls.append(1))
        assert calls == [1]
        remove()  # harmless

    def test_stopping_a_parent_calls_its_descendants_callbacks(self):
        root = StopToken()
        calls = []
        root.child().child().on_stop(lambda: calls.append("grandchild"))
        root.stop()
        assert calls == ["grandchild"]

    def test_an_unregistered_callback_is_not_called(self):
        token = StopToken()
        calls = []
        remove = token.on_stop(lambda: calls.append(1))
        remove()
        remove()  # harmless
        assert not token._callbacks[1]  # Private: nothing kept for a done waiter
        token.stop()
        assert calls == []

    def test_a_function_registered_twice_is_called_twice(self):
        """Each registration is its own: removing one leaves the other."""
        token = StopToken()
        calls = []

        def fn():
            calls.append(1)

        token.on_stop(fn)
        remove = token.on_stop(fn)
        remove()
        token.stop()
        assert calls == [1]

    def test_stop_drops_the_callbacks_it_called(self):
        """A stopped token holds no references to what its waiters captured."""
        token = StopToken()
        token.on_stop(lambda: None)
        token.stop()
        assert token._callbacks is None  # Private: released

    def test_a_callback_may_use_the_token(self):
        """Callbacks run outside the lock: one that registers another callback
        or derives a token does not deadlock."""
        token = StopToken()
        calls = []
        token.on_stop(
            lambda: token.on_stop(lambda: calls.append(token.child().is_set()))
        )
        token.stop()
        assert calls == [True]

    def test_a_failing_callback_is_reported_not_raised(self, monkeypatch):
        """A stop is a broadcast: its caller cannot act on one listener's
        failure, and must not be cut off by it. The error goes to
        threading.excepthook; the rest of the tree is stopped and its
        callbacks called."""
        reported = []
        monkeypatch.setattr(threading, "excepthook", reported.append)
        root = StopToken()
        child = root.child()
        calls = []
        error = ValueError("callback failed")

        def fail():
            raise error

        root.on_stop(fail)
        root.on_stop(lambda: calls.append("root"))
        child.on_stop(lambda: calls.append("child"))
        root.stop()
        assert child.is_set()
        assert sorted(calls) == ["child", "root"]
        assert [args.exc_value for args in reported] == [error]

    def test_an_interrupt_in_a_callback_propagates_once_the_tree_is_stopped(self):
        """KeyboardInterrupt is not a callback's failure to report: it ends
        the stop's callbacks, as an interrupt ends anything. The tree is
        stopped before any callback runs, so no token is left running."""
        root = StopToken()
        child = root.child()

        def interrupt():
            raise KeyboardInterrupt

        root.on_stop(interrupt)
        with pytest.raises(KeyboardInterrupt):
            root.stop()
        assert root.is_set()
        assert child.is_set()

    def test_a_failing_hook_falls_back_and_the_stop_goes_on(self, monkeypatch):
        """The hook reporting a callback's error raises too: as in threading,
        the hook's error goes to sys.excepthook, and the rest of the tree is
        stopped and its callbacks called."""
        hook_error = RuntimeError("hook failed")
        fallback = []

        def failing_hook(args):
            raise hook_error

        monkeypatch.setattr(threading, "excepthook", failing_hook)
        monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: fallback.append(v))
        root = StopToken()
        child = root.child()
        calls = []

        def fail():
            raise ValueError("callback failed")

        root.on_stop(fail)
        child.on_stop(lambda: calls.append("child"))
        root.stop()
        assert child.is_set()
        assert calls == ["child"]
        assert fallback == [hook_error]

    def test_on_a_stopped_token_a_failing_callback_raises_to_its_registrant(self):
        """Called at once, the callback runs for the caller of on_stop(),
        who can handle its error."""
        token = StopToken()
        token.stop()

        def fail():
            raise ValueError("callback failed")

        with pytest.raises(ValueError, match="callback failed"):
            token.on_stop(fail)

    def test_a_pickled_token_carries_no_callbacks(self):
        token = StopToken()
        token.on_stop(lambda: None)
        assert pickle.loads(pickle.dumps(token))._callbacks is None
