# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: Copyright 2026 The appinfra Authors

"""
Database utilities for common operations.

This module provides utility functions for working with SQLAlchemy sessions
and ORM objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from sqlalchemy import inspect
from sqlalchemy.orm import make_transient

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

T = TypeVar("T")


def detach(obj: T | None, session: Session) -> T | None:
    """
    Detach an ORM object from its session for use after session closes.

    Forces loading of all column attributes, then expunges the object
    from the session and marks it as transient. This prevents
    DetachedInstanceError when accessing attributes after the session closes.

    Args:
        obj: The ORM object to detach, or None.
        session: The session the object is attached to.

    Returns:
        The detached object, or None if obj was None.

    Example:
        with session:
            user = session.get(User, user_id)
            return detach(user, session)  # Safe to use after session closes
    """
    if obj is None:
        return None

    # Force load all column attributes
    mapper = inspect(type(obj))
    if mapper is not None:
        for col in mapper.columns:
            getattr(obj, col.key, None)

    # Remove from session and mark as transient
    session.expunge(obj)
    make_transient(obj)

    return obj


def detach_all(objects: list[T], session: Session) -> list[T]:
    """
    Detach multiple ORM objects from their session.

    Args:
        objects: List of ORM objects to detach.
        session: The session the objects are attached to.

    Returns:
        List of detached objects.

    Example:
        with session:
            users = session.scalars(select(User)).all()
            return detach_all(users, session)
    """
    return [detach(obj, session) for obj in objects]  # type: ignore[misc]
