# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""Tests for StopToken."""

from appinfra.service.stop import StopToken


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
