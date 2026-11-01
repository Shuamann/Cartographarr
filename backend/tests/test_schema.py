from sqlalchemy import inspect, text


def missing_indexes() -> list[str]:
    from app.db import Base, engine

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing = []
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        have = {i["name"] for i in inspector.get_indexes(table.name)}
        missing += [i.name for i in table.indexes if i.name not in have]
    return missing


def declared(table_name: str) -> set[str]:
    from app.db import Base

    return {i.name for i in Base.metadata.tables[table_name].indexes}


def test_every_declared_index_exists(client):
    """The one that would have been missed, generalised."""
    assert missing_indexes() == []


def test_an_index_added_later_is_created(client):
    """Added to a table that already exists, which is the case that failed."""
    from app.db import engine, init_db

    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS ix_media_bitrate"))
    assert "ix_media_bitrate" in missing_indexes()

    init_db()

    assert missing_indexes() == []


def test_the_library_table_is_indexed_for_the_pages_that_read_it(client):
    assert declared("media_items") >= {
        "ix_media_section_type", "ix_media_type_size", "ix_media_bitrate",
    }


def test_history_can_order_without_a_temporary_tree(client):
    """A device's or an address's history is always newest first."""
    assert declared("history") >= {
        "ix_history_machine_started", "ix_history_ip_started", "ix_history_rating_started",
    }


# ---- what the connection is told --------------------------------------------

def test_a_locked_database_is_waited_for(client):
    """Zero, the default, raises instead of waiting. Three things write here."""
    from app.db import engine

    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000


def test_the_journal_is_still_write_ahead(client):
    from app.db import engine

    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
