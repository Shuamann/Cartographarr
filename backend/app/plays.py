"""Plays and sessions.

History keeps one row per session. A play that was paused and resumed, or
carried from a phone to a TV, is several sessions sharing Tautulli's reference
id. Both numbers are true and neither is a rounding of the other, so counts
labelled "plays" count each reference id once, and "sessions" counts the rows.

Each helper takes the History class the caller is querying, because the tests
reload the models and two copies of one table cannot be mixed in a query.
"""

from __future__ import annotations

from sqlalchemy import case, func


def key(history):
    """What makes one play: its reference id, or its own row when it has none."""
    return func.coalesce(history.reference_id, history.row_id)


def plays(history):
    return func.count(func.distinct(key(history)))


def sessions():
    return func.count()


def plays_when(history, condition):
    """Plays matching a condition, each counted once."""
    return func.count(func.distinct(case((condition, key(history)))))


def plays_in(sub):
    """Plays in a subquery that carries the history columns."""
    return func.count(func.distinct(func.coalesce(sub.c.reference_id, sub.c.row_id)))
