"""Asking Plex what else an item could be, and taking one of the answers.

A wrong match is the one library problem this app could see from two places
and fix from neither. A film matched to the wrong entry carries the wrong
external ids, so Radarr has nothing under them and the error says so; two
items matched to the same entry are the "Two entries for one title" list. The
remedy in both cases is Plex's own Fix Match, which is two calls, and until
now it meant leaving the app for Plex Web.

The shape was measured against a real server, 1.43.4, and it is not what the
plexapi docstring suggests:

    GET /library/metadata/{key}/matches              one candidate, the
                                                     automatic match
    GET /library/metadata/{key}/matches?manual=1     up to twenty candidates

The `manual=1` is the whole difference, and it is what plexapi's `matches()`
sends. Without it the server answers with the match it already made, which
reads as "there is nothing else this could be".

A candidate is a <SearchResult> carrying, across twenty rows of two films:

    guid            all 20     plex://movie/5d77...
    name            all 20
    type            always     movie, show, season
    lifespanEnded   always     "0"
    guid            always
    name            always
    year            78%        a string, not a number
    summary         79%
    thumb           sometimes, and not read here

Counted over 302 candidates on 17 items: films, shows and episodes.

So: no agent on a candidate, and no score, whatever plexapi's SearchResult
class offers. Both of its attributes for those read as None on every row of
every item tried. The agent belongs to the library rather than to a candidate,
which is why it is reported once for the list. A fifth of the candidates have
no year at all, which matters more than it sounds: the year is the first thing
anybody would sort or guess on, and a fifth of the list cannot be sorted by it.

Two films of the same play in the same year is the case this exists for, so
nothing here picks for anybody. `apply` takes a guid that Plex offered in this
same list and refuses anything else, and the name written to Plex is the one
Plex gave, never a string handed in from outside.

An episode has no match of its own. plexapi puts the mixin on Movie, Show,
Artist and Album only, and the server agrees: an episode's own /matches comes
back size=0, an empty list, while its show's comes back with twenty. The ids
the Radarr and Sonarr lookup uses for an episode are the show's as well, so
what is offered for an episode is its show's match.

Costs, against a real server, over the 17 items above:

    a candidate list, whole, through here    189 to 1269 ms, median 374
    reading the item back afterwards         about 10 ms
    the library's agent                      about 11 ms

All on a path somebody has pressed, so none of it is worth caching, and the
twenty candidates are what Plex gives rather than a page of its own.

The current match was in its own candidate list on all 17, and first on all
17, which is exactly why it is found by its guid instead: nothing says it has
to be, and marking the wrong row as the one in use is worse than not marking
one.
"""

from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

SETTLE_WAITS = (0.25, 0.5, 1.0, 1.5, 2.0)
"""How long to keep asking for the new ids before giving up on them.

A match is applied the moment the PUT returns, but the external ids come from
the agent's own fetch and are not there yet. Shows are the reason this waits
at all: nothing re-reads a show row on a schedule, so the ids written here are
the only ones it will get until something plays. About five seconds in all,
and it stops as soon as an id appears.
"""


def _text(value: Any) -> str | None:
    text = (value or "").strip() if isinstance(value, str) else None
    return text or None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def where(rating_key: int) -> dict[str, Any]:
    """Which item carries the match for this one, from what has been scanned.

    An episode's own match is empty on the server and its ids come from its
    show, so an episode is answered with its show. A film answers with itself.
    """
    from app.db import session_scope
    from app.models import MediaItem

    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None:
            raise LookupError("This app has not scanned that item")
        if item.media_type == "episode":
            show_key = item.grandparent_rating_key
            if show_key is None:
                raise LookupError(
                    "An episode has no match of its own and this app does not know which show it belongs to"
                )
            show = db.get(MediaItem, show_key)
            return {
                "rating_key": show_key,
                "media_type": "show",
                "title": (show.title if show else None) or item.grandparent_title,
                "year": show.year if show else None,
                "asked_about": rating_key,
                "instead_of": "episode",
            }
        return {
            "rating_key": rating_key,
            "media_type": item.media_type,
            "title": item.title,
            "year": item.year,
            "asked_about": rating_key,
            "instead_of": None,
        }


def _agent(plex: Any, item: Any) -> str | None:
    """Which agent produced the list. The library's, since a candidate has
    none of its own. Never worth failing the list over."""
    try:
        return _text(item.section().agent)
    except Exception as exc:  # noqa: BLE001 - the candidates matter, this does not
        log.debug("could not read which agent matched %s: %s", getattr(item, "ratingKey", None), exc)
        return None


def _candidate(element: Any, current_guid: str | None) -> dict[str, Any]:
    guid = _text(element.attrib.get("guid"))
    return {
        "guid": guid,
        "name": _text(element.attrib.get("name")),
        # A string on the wire, and absent on a fifth of them.
        "year": _int(element.attrib.get("year")),
        "media_type": _text(element.attrib.get("type")),
        "summary": _text(element.attrib.get("summary")),
        # What Plex is matched to now, by its guid rather than by its place in
        # the list: the current match came first on every item tried, and
        # trusting that would be trusting an order nothing promises.
        "current": bool(guid) and guid == current_guid,
    }


def candidates(rating_key: int) -> dict[str, Any]:
    """What Plex says this item could be, and which one it is matched to now.

    An empty list is an answer rather than a failure: the agent found nothing,
    and saying so is the difference between "nothing matches this" and a list
    that failed to draw.
    """
    from app.plex.server import server

    target = where(rating_key)
    plex = server()
    item = plex.fetchItem(int(target["rating_key"]))
    current_guid = _text(getattr(item, "guid", None))
    data = plex.query(f"/library/metadata/{int(target['rating_key'])}/matches?manual=1")
    found = [_candidate(child, current_guid) for child in data if child.tag == "SearchResult"]
    return {
        **target,
        # What Plex itself holds, which can differ from the row this app has:
        # that disagreement is the problem being looked at.
        "plex_title": _text(getattr(item, "title", None)),
        "plex_year": _int(getattr(item, "year", None)),
        "current_guid": current_guid,
        "agent": _agent(plex, item),
        "candidates": [row for row in found if row["guid"]],
    }


def _settled(plex: Any, rating_key: int, guid: str | None) -> Any:
    """The item, read back once its new ids have arrived, or as late as we wait.

    Never raises on the waiting: having the match applied and not having the
    ids yet is a worse answer than before only if it is reported as a failure.
    """
    from app.plex import library as plex_library

    item = plex.fetchItem(int(rating_key))
    for wait in SETTLE_WAITS:
        took = _text(getattr(item, "guid", None)) == guid if guid else True
        if took and any(plex_library.external_ids(item).values()):
            return item
        time.sleep(wait)
        try:
            item = plex.fetchItem(int(rating_key))
        except Exception as exc:  # noqa: BLE001 - the match itself was applied
            log.warning("could not read %s back after its match changed: %s", rating_key, exc)
            return item
    return item


def _agreed(rating_key: int, item: Any, media_type: str | None) -> dict[str, Any]:
    """Make this app's row say what Plex now says, ids and all.

    The ids are the point. They came from the old match, they are now wrong,
    and every one of them is written here even when the new match has none,
    because the pass that fills them in later keeps only the values it has:
    left to it, a film re-matched to something with no TMDB id would keep the
    old film's TMDB id for ever. A missing id is honest and a wrong one is the
    whole problem.

    Episodes under a re-matched show are emptied rather than read: their guids
    changed too, there can be hundreds of them, and the detail pass reads an
    episode whose file_checked_at is clear within the minute. For the minute
    in between they say they have no id, which is true.
    """
    from sqlalchemy import update

    from app.db import session_scope
    from app.models import MediaItem
    from app.plex import library as plex_library

    ids = plex_library.external_ids(item)
    changed: dict[str, Any] = {}
    with session_scope() as db:
        row = db.get(MediaItem, rating_key)
        if row is None:
            return {"ids": ids, "changed": changed, "episodes_cleared": 0}
        for name, value in ids.items():
            if getattr(row, name) != value:
                changed[name] = {"was": getattr(row, name), "now": value}
            setattr(row, name, value)
        title = _text(getattr(item, "title", None))
        if title and title != row.title:
            changed["title"] = {"was": row.title, "now": title}
            row.title = title
            if row.media_type != "episode":
                row.full_title = title
        year = _int(getattr(item, "year", None))
        if year is not None and year != row.year:
            changed["year"] = {"was": row.year, "now": year}
            row.year = year
        thumb = _text(getattr(item, "thumb", None))
        if thumb:
            row.thumb = thumb
        # Read again rather than kept: the tracks have not changed, but the
        # summary, the artwork and what the film is said to be all have.
        row.file_checked_at = None
        episodes = 0
        if media_type == "show":
            episodes = db.execute(
                update(MediaItem)
                .where(MediaItem.grandparent_rating_key == rating_key, MediaItem.media_type == "episode")
                .values(imdb_id=None, tmdb_id=None, tvdb_id=None, file_checked_at=None)
            ).rowcount or 0
    return {"ids": ids, "changed": changed, "episodes_cleared": episodes}


def apply(rating_key: int, guid: str) -> dict[str, Any]:
    """Match this item to one of the candidates Plex offered, and agree with it.

    The guid has to be one from this item's own list. Not a guard against
    somebody being clever: it is what makes the name sent to Plex the name
    Plex gave, and it catches the real case of a list read an hour ago and
    acted on after somebody else changed the match.
    """
    from app.plex.server import server

    target = where(rating_key)
    match_key = int(target["rating_key"])
    plex = server()
    item = plex.fetchItem(match_key)
    was = _text(getattr(item, "guid", None))
    offered = item.matches()
    chosen = next((m for m in offered if _text(getattr(m, "guid", None)) == guid), None)
    if chosen is None:
        if not offered:
            raise LookupError("Plex offers nothing to match this to, so there is nothing to choose")
        raise LookupError("Plex is not offering that match any more, so the list has to be read again")
    item.fixMatch(searchResult=chosen)
    name = _text(getattr(chosen, "name", None))
    settled = _settled(plex, match_key, guid)
    agreed = _agreed(match_key, settled, target["media_type"])
    return {
        **target,
        "was_guid": was,
        "guid": guid,
        "name": name,
        "year": _int(getattr(chosen, "year", None)),
        # Said rather than assumed: an id that had not arrived by the time we
        # stopped waiting is filled in by the next read, and for a show that
        # is the next time something plays.
        "ids": agreed["ids"],
        "ids_arrived": any(agreed["ids"].values()),
        "changed": agreed["changed"],
        "episodes_cleared": agreed["episodes_cleared"],
    }
