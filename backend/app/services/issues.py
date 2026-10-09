"""Reports of something wrong with a file.

Seerr collects them ("audio is out of sync", "no subtitles"), but on its own a
report is a sentence. This app already knows the file's tracks, bitrate and
resolution, who played it on what device, whether it transcoded for them, and
whether it stalled while they watched. Pulling the reports in puts the sentence
next to the evidence, and next to the replacement workflow that can fix it.

Issues live here. Seerr is a second place they come from, and what is
decided here goes back to it: a comment, a resolution, a reopening.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.db import session_scope
from app.integrations.base import get_json
from app.integrations.seerr import seerr

log = logging.getLogger(__name__)

# Seerr's numbers, in the order its own UI lists them.
TYPES = {1: "video", 2: "audio", 3: "subtitles", 4: "other"}
STATUS = {1: "open", 2: "resolved"}
LABELS = {"video": "Video", "audio": "Audio", "subtitles": "Subtitles", "other": "Other"}
PAGE = 100


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _when(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _person(raw: Any) -> tuple[str | None, int | None]:
    """Who reported or commented, and their Plex user id where there is one.

    Seerr does not always send the whole user: a comment can arrive with the
    user cut down to its ids, or as a bare Seerr id. Whatever is missing here
    is filled in by _author from the people the same sync has already seen.
    """
    if not isinstance(raw, dict):
        return None, None
    name = raw.get("displayName") or raw.get("plexUsername") or raw.get("username") or raw.get("email")
    return name, _int(raw.get("plexId"))


def _seerr_id(raw: Any) -> int | None:
    return _int(raw.get("id")) if isinstance(raw, dict) else _int(raw)


def _directory(raws: list[dict[str, Any]]) -> dict[int, tuple[str | None, int | None]]:
    """Every Seerr user named anywhere in this sync, by their Seerr id.

    A person who reported one issue and only commented on another is still the
    same person, and Seerr's users are Plex logins, so whoever is named once
    can be named everywhere.
    """
    people: dict[int, tuple[str | None, int | None]] = {}
    for raw in raws:
        users = [raw.get("createdBy"), raw.get("modifiedBy")] + [c.get("user") for c in raw.get("comments") or []]
        for user in users:
            sid, (name, plex_id) = _seerr_id(user), _person(user)
            if sid is not None and (name or plex_id):
                known = people.get(sid, (None, None))
                people[sid] = (known[0] or name, known[1] or plex_id)
    return people


def _author(db, user: Any, people: dict[int, tuple[str | None, int | None]]) -> tuple[str | None, int | None]:
    """A comment's author by name, from the comment, from the sync, or from
    the Plex users this app already knows."""
    from app.models import User

    name, plex_id = _person(user)
    if not (name and plex_id):
        known = people.get(_seerr_id(user) or -1, (None, None))
        name, plex_id = name or known[0], plex_id or known[1]
    if name is None and plex_id is not None:
        found = db.get(User, plex_id)
        if found is not None:
            name = found.friendly_name or found.username
    return name, plex_id


def episode_key(db, show_rating_key: int | None, season: int | None, episode: int | None) -> int | None:
    """The episode's own rating key, so an issue lands on the file itself."""
    from app.models import MediaItem

    if not (show_rating_key and season and episode):
        return None
    return db.execute(
        select(MediaItem.rating_key).where(
            MediaItem.grandparent_rating_key == show_rating_key,
            MediaItem.parent_media_index == season,
            MediaItem.media_index == episode,
        )
    ).scalar()


def _match(db, media: dict[str, Any], season: int | None, episode: int | None,
           name: str | None) -> tuple[int | None, int | None, str | None]:
    """The file an issue is about: (rating key, show key, how it was found).

    Seerr's rating key first, since it is Plex's own and the same one this app
    uses. Plex renumbers things, though, and a report outlives the key it was
    made against, so the ids come next: every title in the library now carries
    them. An episode's ids are the episode's own, not the show's, so a show is
    found through a show row where one exists and otherwise by the name Seerr
    gives it, and only when that name means one show here: a guess at a file
    is worse than no file.

    How is None when nothing here matched; the reported key is kept anyway, so
    the report still says what it was about.
    """
    from app.models import MediaItem

    key = _int(media.get("ratingKey")) or _int(media.get("ratingKey4k"))
    if media.get("mediaType") == "tv":
        shows: list[tuple[int, str]] = [(key, "rating_key")] if key else []
        for column, value, how in ((MediaItem.tvdb_id, media.get("tvdbId"), "tvdb"),
                                   (MediaItem.tmdb_id, media.get("tmdbId"), "tmdb")):
            if value:
                shows += [(k, how) for k in db.execute(
                    select(MediaItem.rating_key).where(MediaItem.media_type == "show", column == str(value))
                ).scalars()]
        if name:
            named = db.execute(
                select(MediaItem.grandparent_rating_key).where(
                    MediaItem.media_type == "episode", func.lower(MediaItem.grandparent_title) == name.strip().lower(),
                ).distinct().limit(2)
            ).scalars().all()
            if len(named) == 1 and named[0] is not None:
                shows.append((named[0], "title"))
        for show, how in shows:
            found = episode_key(db, show, season, episode)
            if found:
                return found, show, how
            if episode is None and db.execute(
                select(MediaItem.rating_key).where(MediaItem.grandparent_rating_key == show).limit(1)
            ).first():
                return show, show, how
        return key, key, None

    if key:
        item = db.get(MediaItem, key)
        if item is not None and item.title is not None:
            return key, None, "rating_key"
    for column, value, how in ((MediaItem.tmdb_id, media.get("tmdbId"), "tmdb"),
                               (MediaItem.imdb_id, media.get("imdbId"), "imdb")):
        if value:
            found = db.execute(
                select(MediaItem.rating_key).where(MediaItem.media_type == "movie", column == str(value)).limit(1)
            ).scalar()
            if found:
                return found, None, how
    return key, None, None


def row_from_issue(db, raw: dict[str, Any], people: dict[int, tuple[str | None, int | None]] | None = None) -> dict[str, Any] | None:
    """One issues row from Seerr's issue, or None if it names no media.

    The row carries how its file was found under "_how", for counting; the
    caller takes it off before storing.
    """
    from app.models import MediaItem

    seerr_id = _int(raw.get("id"))
    if seerr_id is None:
        return None
    media = raw.get("media") or {}
    season, episode = _int(raw.get("problemSeason")), _int(raw.get("problemEpisode"))
    # Seerr sends 0 and 0 for a film, which would otherwise read as season
    # nought, a special, and there is no episode nought of anything.
    if media.get("mediaType") != "tv" or not episode:
        season = episode = None
    key, show_key, how = _match(db, media, season, episode, raw.get("_name"))
    name, reporter_id = _author(db, raw.get("createdBy"), people or {})
    item = db.get(MediaItem, key) if key else None
    comments = []
    for c in raw.get("comments") or []:
        author, author_id = _author(db, c.get("user"), people or {})
        comments.append({
            "message": c.get("message"),
            "author": author,
            "author_id": author_id,
            "created_at": (_when(c.get("createdAt")) or datetime.now(UTC).replace(tzinfo=None)).isoformat(),
        })
    return {
        "seerr_id": seerr_id,
        "source": "seerr",
        "issue_type": TYPES.get(_int(raw.get("issueType")) or 4, "other"),
        "status": STATUS.get(_int(raw.get("status")) or 1, "open"),
        "message": (raw.get("comments") or [{}])[0].get("message"),
        "media_type": media.get("mediaType"),
        "tmdb_id": _int(media.get("tmdbId")),
        "tvdb_id": _int(media.get("tvdbId")),
        "rating_key": key,
        "show_rating_key": show_key,
        "season": season,
        "episode": episode,
        # A report on something not here keeps the name Seerr knows it by, so
        # it still says what it was about.
        "title": ((item.full_title or item.title) if item is not None and item.title else None) or raw.get("_name"),
        "reporter_name": name,
        "reporter_user_id": reporter_id,
        "comments": json.dumps(comments),
        "created_at": _when(raw.get("createdAt")),
        "updated_at": _when(raw.get("updatedAt")),
        "synced_at": datetime.now(UTC).replace(tzinfo=None),
        "_how": how,
    }


# ---- reading Seerr -----------------------------------------------------------

_CLIENT: ContextVar[Any] = ContextVar("seerr_client", default=None)


@asynccontextmanager
async def _connection():
    """One connection for a whole read: a page of issues, every new one's
    comments and the names of whatever did not match are dozens of requests,
    and a client each would be a handshake each."""
    if _CLIENT.get() is not None:
        yield
        return
    import httpx

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        token = _CLIENT.set(client)
        try:
            yield
        finally:
            _CLIENT.reset(token)


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{seerr.base_url}/api/v1{path}"
    client = _CLIENT.get()
    if client is None:
        return await get_json(url, headers=seerr.headers, params=params)
    response = await client.get(url, headers=seerr.headers, params=params)
    response.raise_for_status()
    return response.json()


async def media_name(media: dict[str, Any]) -> str | None:
    """What Seerr calls a film or show, for a report this app cannot place."""
    kind, tmdb = media.get("mediaType"), _int(media.get("tmdbId"))
    if kind not in ("movie", "tv") or not tmdb:
        return None
    data = await _get(f"/{kind}/{tmdb}") or {}
    return data.get("title") or data.get("name") or None


def _unplaced(raws: list[dict[str, Any]]) -> list[int]:
    """The issues whose rating key finds nothing here, by Seerr id: the ones
    worth asking Seerr the name of."""
    with session_scope() as db:
        out = []
        for raw in raws:
            media = raw.get("media") or {}
            season, episode = _int(raw.get("problemSeason")), _int(raw.get("problemEpisode"))
            if media.get("mediaType") != "tv" or not episode:
                season = episode = None
            if _match(db, media, season, episode, None)[2] is None:
                out.append(_int(raw.get("id")))
        return out


async def _name_the_unplaced(raws: list[dict[str, Any]]) -> None:
    import asyncio

    wanted = set(await asyncio.to_thread(_unplaced, raws))
    for raw in raws:
        if _int(raw.get("id")) in wanted:
            try:
                raw["_name"] = await media_name(raw.get("media") or {})
            except Exception as exc:  # noqa: BLE001 - a report without a name is still a report
                log.debug("no name for issue %s: %s", raw.get("id"), exc)


async def fetch(limit: int | None = None) -> list[dict[str, Any]]:
    """Every issue Seerr has, newest first, a page at a time.

    All of them by default. A cap here once meant the oldest reports were
    never read at all, and a report not read is a report that, as far as this
    app is concerned, nobody made.
    """
    out: list[dict[str, Any]] = []
    while limit is None or len(out) < limit:
        data = await _get("/issue", {"take": PAGE, "skip": len(out), "filter": "all", "sort": "added"})
        results = (data or {}).get("results") or []
        out.extend(results)
        total = ((data or {}).get("pageInfo") or {}).get("results")
        if len(results) < PAGE or (total is not None and len(out) >= int(total)):
            break
    return out if limit is None else out[:limit]


async def detail(seerr_id: int) -> dict[str, Any]:
    """One issue with its comments, which the list leaves out."""
    return await _get(f"/issue/{seerr_id}")


def _known() -> dict[int, str | None]:
    from app.models import Issue

    with session_scope() as db:
        return {
            # A report whose comments have no author is read again in full,
            # since a copy from the list may have been what lost them.
            i.seerr_id: (i.updated_at.isoformat() if i.updated_at else None) if _named(i.comments) else "unnamed"
            for i in db.execute(select(Issue).where(Issue.seerr_id.is_not(None))).scalars()
        }


async def _read(only_new: bool) -> tuple[list[dict[str, Any]], int]:
    """Every issue, each in full where it is new (or changed, unless only new
    ones are wanted), with names for those this app cannot place."""
    import asyncio

    listed = await fetch()
    seen = await asyncio.to_thread(_known)
    wanted = [
        r for r in listed
        if _int(r.get("id")) not in seen
        or (not only_new and (_when(r.get("updatedAt")) or datetime.min).isoformat() != seen.get(_int(r.get("id"))))
    ]
    full = {}
    for raw in wanted:
        seerr_id = _int(raw.get("id"))
        try:
            full[seerr_id] = await detail(seerr_id)
        except Exception as exc:  # noqa: BLE001 - one unreadable issue must not stop the read
            log.debug("issue %s unreadable: %s", seerr_id, exc)
    rows = [full.get(_int(r.get("id")), r) for r in listed]
    await _name_the_unplaced(rows)
    return rows, len(full)


async def sync(limit: int | None = None) -> dict[str, int]:
    """Pull issues from Seerr. Comments are read for issues that changed."""
    import asyncio

    async with _connection():
        rows, read = await _read(only_new=False)
    before = await asyncio.to_thread(_open_ids)
    stored = await asyncio.to_thread(_store, rows)
    # Word goes out for reports this app had not seen before, not for every
    # report in Seerr the first time it looks.
    told = 0
    if before is not None:
        for issue_id in sorted(set(await asyncio.to_thread(_open_ids)) - set(before)):
            told += 1 if await announce(issue_id) else 0
    return {"issues": stored["stored"], "read": read, "told": told, "new": stored["new"],
            "no_longer_in_seerr": stored["gone"]}


async def import_all() -> dict[str, Any]:
    """Bring in everything Seerr holds, and say what came of it.

    The same reading and the same storing as the sync, which already keeps
    reports current, so a report already here is recognised by Seerr's own id
    and not brought in twice. What this adds is the answer: how many were
    read, how many were new, how many were already here, and which could not
    be put against a file and were kept anyway. Nobody is told about these,
    since they are history rather than news.
    """
    import asyncio

    async with _connection():
        rows, _ = await _read(only_new=True)
    stored = await asyncio.to_thread(_store, rows)
    return {
        "read": len(rows),
        "new": stored["new"],
        "already_here": stored["stored"] - stored["new"],
        "unmatched": len(stored["unmatched"]),
        "unmatched_titles": stored["unmatched"][:20],
        "matched_by": stored["matched_by"],
        "no_longer_in_seerr": stored["gone"],
    }


def _open_ids() -> list[int] | None:
    """Every report from Seerr this app knows, or None the first time."""
    from app.models import Issue, SyncState

    with session_scope() as db:
        first = db.get(SyncState, "issues_seen") is None
        ids = [i.id for i in db.execute(select(Issue).where(Issue.seerr_id.is_not(None))).scalars()]
        if first:
            db.merge(SyncState(key="issues_seen", value="1"))
            return None
        return ids


def _named(comments: str | None) -> bool:
    try:
        return all(c.get("author") for c in json.loads(comments or "[]"))
    except (ValueError, AttributeError):
        return False


def _keep_authors(old: str | None, new: str | None) -> str | None:
    """New comments, keeping any author the old copy knew and the new one does
    not. The list Seerr returns can carry less than the issue read on its own,
    and a sync that has nothing new to say must not unsay a name."""
    try:
        before, after = json.loads(old or "[]"), json.loads(new or "[]")
    except ValueError:
        return new
    if not after and before:
        return old
    known = {(c.get("created_at"), c.get("message")): c for c in before if c.get("author")}
    for c in after:
        if not c.get("author"):
            match = known.get((c.get("created_at"), c.get("message")))
            if match:
                c["author"], c["author_id"] = match.get("author"), match.get("author_id")
    return json.dumps(after)


def _store(raws: list[dict[str, Any]]) -> dict[str, Any]:
    """Write what Seerr said, and count it.

    Nothing is deleted on Seerr's say-so. A report Seerr no longer lists,
    whether somebody deleted it there, Seerr was reinstalled, or it answered
    with an empty list one evening, is marked and kept: this app is where
    reports live, and losing them because another service forgot them is the
    one outcome a system of record exists to prevent.
    """
    from app.models import Issue

    counts: dict[str, Any] = {"stored": 0, "new": 0, "gone": 0, "unmatched": [], "matched_by": {}}
    people = _directory(raws)
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        existing = {i.seerr_id: i for i in db.execute(select(Issue).where(Issue.seerr_id.is_not(None))).scalars()}
        seen: set[int] = set()
        for raw in raws:
            row = row_from_issue(db, raw, people)
            if row is None:
                continue
            how = row.pop("_how")
            if how is None:
                counts["unmatched"].append(row["title"] or f"Seerr issue {row['seerr_id']}")
            else:
                counts["matched_by"][how] = counts["matched_by"].get(how, 0) + 1
            seen.add(row["seerr_id"])
            row["seerr_gone_at"] = None
            issue = existing.get(row["seerr_id"])
            if issue is None:
                db.add(Issue(**row))
                counts["new"] += 1
            else:
                row["comments"] = _keep_authors(issue.comments, row["comments"])
                if row["message"] is None:
                    row["message"] = issue.message
                for key, value in row.items():
                    # A title, or the file it was about, can leave Plex while
                    # the report stands. Forgetting what it was called would
                    # leave "Unknown title" where the answer is already known.
                    if value is None and key in ("title", "rating_key", "show_rating_key") and getattr(issue, key) is not None:
                        continue
                    setattr(issue, key, value)
            counts["stored"] += 1
        for seerr_id, issue in existing.items():
            if seerr_id not in seen and issue.seerr_gone_at is None:
                issue.seerr_gone_at = now
                counts["gone"] += 1
    return counts


# ---- writing back ----------------------------------------------------------
#
# Seerr's API key acts as the admin account, so anything posted from here would
# read as the admin having said it. Every message therefore names whoever acted,
# which is also what makes an auto-resolve honest about being automatic.

async def _post(path: str, body: dict[str, Any] | None = None) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(f"{seerr.base_url}/api/v1{path}", headers=seerr.headers, json=body or {})
        response.raise_for_status()


def signed(message: str, author: str | None) -> str:
    return f"{message}\n\n({author} via Cartographarr)" if author else f"{message}\n\n(via Cartographarr)"


async def comment(seerr_id: int, message: str, author: str | None = None) -> None:
    await _post(f"/issue/{seerr_id}/comment", {"message": signed(message, author)})


async def set_status(seerr_id: int, status: str, author: str | None = None, note: str | None = None) -> None:
    """Resolve or reopen in Seerr. A note is posted first, so the person who
    reported it can see why it closed rather than just that it did."""
    if note:
        await comment(seerr_id, note, author)
    await _post(f"/issue/{seerr_id}/{'resolved' if status == 'resolved' else 'open'}")


async def _mirror(issue_id: int, send) -> str | None:
    """Do the Seerr half of a change made here.

    A failure is reported rather than raised: the decision was made in this
    app, and the next sync would only half write it back anyway.
    """
    from app.models import Issue

    with session_scope() as db:
        issue = db.get(Issue, issue_id)
        seerr_id = issue.seerr_id if issue else None
        gone = bool(issue and issue.seerr_gone_at)
    if not (seerr_id and seerr.configured()):
        return None
    if gone:
        return "Seerr no longer has this report, so the change is kept here only."
    try:
        await send(seerr_id)
    except Exception as exc:  # noqa: BLE001 - Seerr being down is not a reason to lose the note
        from app.integrations.base import describe_failure

        return f"Seerr was not updated: {describe_failure(exc)}"
    return None


def _notes(issue) -> list[dict[str, Any]]:
    try:
        return json.loads(issue.comments or "[]")
    except ValueError:
        return []


async def add_comment(issue_id: int, message: str, author: str | None) -> tuple[str, int, str | None]:
    """Add a note to a report, here and in Seerr.

    Returns the report's title, how many notes it now has, and a warning if
    Seerr could not be told. Used by the Issues page and by rules, so a note
    left by a rule reads the same as one left by a person.
    """
    from app.models import Issue

    text = message.strip()
    if not text:
        raise ValueError("Nothing to add")
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as db:
        issue = db.get(Issue, issue_id)
        if issue is None:
            raise LookupError("No such issue")
        notes = _notes(issue)
        notes.append({"message": text, "author": author, "created_at": now.isoformat()})
        issue.comments = json.dumps(notes)
        issue.updated_at = now
        title = issue.title
    warning = await _mirror(issue_id, lambda seerr_id: comment(seerr_id, text, author))
    return title, len(notes), warning


async def mark(issue_id: int, status: str, author: str | None, note: str | None = None) -> tuple[str, str | None]:
    """Resolve or reopen a report, here and in Seerr."""
    from app.models import Issue

    if status not in ("open", "resolved"):
        raise ValueError("Status is open or resolved")
    with session_scope() as db:
        issue = db.get(Issue, issue_id)
        if issue is None:
            raise LookupError("No such issue")
        issue.status = status
        # Somebody deciding it now, so it is theirs and not the replacement's.
        issue.replaced_at = None
        issue.updated_at = datetime.now(UTC).replace(tzinfo=None)
        title = issue.title
    warning = await _mirror(issue_id, lambda seerr_id: set_status(seerr_id, status, author, note))
    return title, warning


async def resolve_for_file(rating_key: int, note: str) -> list[int]:
    """Close what this file's replacement was about.

    A report says the audio is broken; the file it was about has just been
    replaced. Leaving it open makes the list untrustworthy, so it closes with
    a note saying what happened, here and in Seerr.
    """
    import asyncio
    import json as json_module
    from datetime import datetime

    from app.models import Issue

    def take() -> list[tuple[int, int | None]]:
        now = datetime.now(UTC).replace(tzinfo=None)
        found = []
        with session_scope() as db:
            for issue in db.execute(
                select(Issue).where(Issue.rating_key == rating_key, Issue.status == "open")
            ).scalars():
                notes = json_module.loads(issue.comments or "[]")
                notes.append({"message": note, "author": "Cartographarr", "created_at": now.isoformat()})
                issue.comments = json_module.dumps(notes)
                issue.status = "resolved"
                issue.updated_at = now
                issue.replaced_at = now
                found.append((issue.id, issue.seerr_id))
        return found

    closed = await asyncio.to_thread(take)
    if seerr.configured():
        for _, seerr_id in closed:
            if seerr_id:
                try:
                    await set_status(seerr_id, "resolved", "Cartographarr", note)
                except Exception as exc:  # noqa: BLE001 - the local copy is closed either way
                    log.warning("could not resolve issue %s in Seerr: %s", seerr_id, exc)
    return [issue_id for issue_id, _ in closed]


# ---- telling somebody -------------------------------------------------------

async def announce(issue_id: int) -> bool:
    """Send word of a new report, if notifications are set up.

    One message per report, when it arrives, with enough in it to decide
    whether to get up: what, who, what kind, and what this app already knows is
    wrong with the file.
    """
    from app.integrations.notify import apprise_notifier
    from app.models import Issue, MediaItem
    from app.settings_store import current

    if not current().issue_alerts or not apprise_notifier.configured():
        return False

    def describe() -> tuple[str, str] | None:
        with session_scope() as db:
            issue = db.get(Issue, issue_id)
            if issue is None:
                return None
            lines = [issue.message or "No message."]
            who = issue.reporter_name or "Someone"
            what = issue.title or (f"item {issue.rating_key}" if issue.rating_key else "something")
            lines.append(f"Reported by {who}, {LABELS.get(issue.issue_type, 'Other').lower()}.")
            item = db.get(MediaItem, issue.rating_key) if issue.rating_key else None
            if item is not None:
                from app.services.library import describe_file, file_issues

                known = file_issues(item)
                if known:
                    from app.services.library import ISSUES

                    named = [ISSUES.get(key, key.replace("_", " ")) for key in known]
                    lines.append("Already known about this file: " + "; ".join(named) + ".")
                elif describe_file(item).get("file_bitrate"):
                    lines.append("Nothing about the file itself stands out.")
            if issue.context:
                try:
                    context = json.loads(issue.context)
                    where = " on ".join(x for x in [context.get("player"), context.get("platform")] if x)
                    if where:
                        lines.append(f"Watching on {where}.")
                except ValueError:
                    pass
            return f"{what}: something is wrong", "\n".join(lines)

    import asyncio

    told = await asyncio.to_thread(describe)
    if told is None:
        return False
    try:
        await apprise_notifier.send(*told)
    except Exception as exc:  # noqa: BLE001 - a missed message must not lose the report
        log.warning("could not send word of issue %s: %s", issue_id, exc)
        return False
    return True
