# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for StopToken."""

import pickle
import sys

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

    def test_a_failing_callback_does_not_end_the_walk(self):
        """The rest of the tree is stopped and its callbacks called; the first
        error is raised once the walk is done."""
        root = StopToken()
        child = root.child()
        calls = []

        def fail():
            raise ValueError("first")

        root.on_stop(fail)
        root.on_stop(lambda: calls.append("root"))
        child.on_stop(lambda: calls.append("child"))
        with pytest.raises(ValueError, match="first"):
            root.stop()
        assert child.is_set()
        assert sorted(calls) == ["child", "root"]

    def test_a_pickled_token_carries_no_callbacks(self):
        token = StopToken()
        token.on_stop(lambda: None)
        assert pickle.loads(pickle.dumps(token))._callbacks is None
