"""Who the server is shared with, read from Plex.

The id is the whole difficulty. Plex offers two lists of accounts and they are
not the same numbers: the share list uses the Plex account id, which is what
history, every ban and every privacy scope key on, while systemAccounts
numbers accounts against the server and calls the owner 1. Measured against a
real server: every one of the share list's 34 ids was already in the users
table, against 13 of systemAccounts' 47 that are in no id space this app uses.
"""

import json
from types import SimpleNamespace

from app.plex import people


def a_user(**over):
    base = dict(id=590585209, title="A Guest", username="aguest", email="guest@example.test",
                thumb="/thumb/1", home=False, allowSync=True, servers=[])
    return SimpleNamespace(**{**base, **over})


def a_share(machine_identifier, *sections):
    return SimpleNamespace(
        machineIdentifier=machine_identifier,
        sections=lambda: [SimpleNamespace(id=s, title=f"Section {s}") for s in sections],
    )


def a_plex(users, owner=None, machine_identifier="server-a"):
    account = owner or SimpleNamespace(id=2863368, title="Shua", username="ShuaTheater",
                                       email="owner@example.test", thumb=None, home=True, allowSync=True)
    account.users = lambda: users
    return SimpleNamespace(
        myPlexAccount=lambda: account,
        machineIdentifier=machine_identifier,
        library=SimpleNamespace(sections=lambda: []),
    )


def test_the_owner_is_included_even_though_nobody_shares_with_themselves(monkeypatch):
    monkeypatch.setattr("app.plex.server.server", lambda: a_plex([]))
    rows = people.read()
    assert [r["user_id"] for r in rows] == [2863368]
    assert rows[0]["is_home_user"] is True and rows[0]["friendly_name"] == "Shua"


def test_a_shared_person_keeps_the_name_the_rest_of_the_app_files_them_under():
    row = people._row(a_user())
    assert row["user_id"] == 590585209
    assert row["username"] == "aguest" and row["friendly_name"] == "A Guest"
    assert row["email"] == "guest@example.test" and row["is_home_user"] is False


def test_somebody_with_no_display_name_is_called_by_their_username():
    assert people._row(a_user(title=None))["friendly_name"] == "aguest"


def test_nobody_read_from_plex_is_marked_as_dropped_by_tautulli():
    """It is Tautulli's word for someone it has removed from its own list.
    Nothing read from Plex has ever been in that list, so saying it is true
    would put a warning beside every person on a Plex install."""
    assert people._row(a_user())["deleted_in_tautulli"] is False


def test_the_libraries_are_the_ones_shared_on_this_server(monkeypatch):
    """Somebody shared with on two servers has different access on each, and
    plexapi lists whichever it lists first."""
    guest = a_user(servers=[a_share("server-b", 90), a_share("server-a", 1, 2)])
    monkeypatch.setattr("app.plex.server.server", lambda: a_plex([guest]))
    rows = people.read()
    assert json.loads(rows[1]["shared_libraries"]) == ["1", "2"]


def test_a_share_that_will_not_say_still_leaves_the_person_listed(monkeypatch):
    """Access review is a bonus on top of knowing who exists. Losing the whole
    person because their section list would not load is the wrong trade."""

    def angry():
        raise RuntimeError("Plex said no")

    guest = a_user(servers=[SimpleNamespace(machineIdentifier="server-a", sections=angry)])
    monkeypatch.setattr("app.plex.server.server", lambda: a_plex([guest]))
    rows = people.read()
    assert [r["user_id"] for r in rows] == [2863368, 590585209]
    assert json.loads(rows[1]["shared_libraries"]) == []


def test_the_sections_become_the_libraries_table(monkeypatch):
    plex = a_plex([])
    plex.library = SimpleNamespace(sections=lambda: [
        SimpleNamespace(key="1", title="Films", type="movie"),
        SimpleNamespace(key="2", title="Shows", type="show"),
        SimpleNamespace(key="not a number", title="Odd", type="movie"),
    ])
    monkeypatch.setattr("app.plex.server.server", lambda: plex)
    assert people.libraries() == [
        {"section_id": 1, "name": "Films", "type": "movie"},
        {"section_id": 2, "name": "Shows", "type": "show"},
    ]


def test_somebody_removed_from_the_share_keeps_their_history(client, monkeypatch):
    """Two people on the real server are in the users table and not on the
    share list any more. A row vanishing would orphan four years of plays."""
    import asyncio

    from app.db import session_scope
    from app.models import User
    from app.services import sync
    from tests.test_auth import claim

    claim(client)
    with session_scope() as db:
        db.add(User(user_id=111, username="long-gone", friendly_name="Long Gone"))

    monkeypatch.setattr(people, "read", lambda machine_identifier=None: [people._row(a_user())])
    monkeypatch.setattr(people, "libraries", lambda: [])
    asyncio.run(sync.plex_people())
    with session_scope() as db:
        assert db.get(User, 111) is not None
        assert db.get(User, 590585209) is not None
