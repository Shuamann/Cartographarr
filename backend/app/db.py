"""Database engine and session.

SQLite with WAL so the sync job writing doesn't block the API reading.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import logging

from app.config import get_settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{settings.db_path}", future=True)

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _record):  # noqa: ANN001
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        # SQLite's default is to give up the instant it meets a locked
        # database rather than wait, which is the wrong answer here: the
        # enforcer writes every five seconds, the sync writes in batches and
        # request handlers write on top of both. The transactions are all
        # short, so the overlaps are brief and five seconds is far more than
        # any of them needs; it is there so a brief one is waited out instead
        # of being raised into somebody's page.
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    import app.models  # noqa: F401  (registers the tables on Base)

    Base.metadata.create_all(engine)
    _add_missing_columns()
    _add_missing_indexes()


def _add_missing_indexes() -> None:
    """Create indexes the models declare but the database has not got.

    `create_all` checks whether each table exists and skips the whole of one
    that does, indexes included, so an index added to a model that already has
    rows would never be created. That was handled for one index by hand, which
    is evidence of the problem rather than a solution to it: the next one would
    have been invisible in the same way, and silently, since a missing index
    costs speed and nothing else.

    The same shape as `_add_missing_columns`, and the same limit: this adds
    what is missing and never drops or alters what is there.
    """
    from sqlalchemy import inspect

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {i["name"] for i in inspector.get_indexes(table.name)}
            for index in table.indexes:
                if index.name in have:
                    continue
                index.create(conn, checkfirst=True)
                log.info("Added index %s on %s", index.name, table.name)


def _add_missing_columns() -> None:
    """Add columns that exist on the models but not yet in the database.

    create_all only creates missing tables, never alters existing ones, so
    adding a field to a model would silently do nothing on an install that
    already has data. This covers the only schema change SQLite makes easy,
    which so far is all that has been needed. Anything harder than adding a
    nullable column is the point to reach for a real migration tool.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                if not column.nullable and column.default is None:
                    log.warning(
                        "Cannot add required column %s.%s automatically", table.name, column.name
                    )
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column.type.compile(engine.dialect)}"
                conn.execute(text(ddl))
                log.info("Added column %s.%s", table.name, column.name)
