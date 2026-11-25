# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for StopToken."""

import pickle
import sys

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
