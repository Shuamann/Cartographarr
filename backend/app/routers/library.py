"""Library health. Admin only: file paths and who watches what."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query
from sqlalchemy import case, func, select

from app import audit
from app.auth.deps import AdminUser
from app.db import session_scope
from app.models import History, MediaItem, StreamEvent, StreamSession
from app.routers.data import Db
from app.services import library
from app.settings_store import current

router = APIRouter(prefix="/api/library")

Days = Query(90, ge=1, le=3650)


@router.get("/collections")
def collections(_: AdminUser, db: Db, days: int = Days) -> list:
    """Each collection's size, problem files and how much of it is watched.

    Also the list the kept collections setting is picked from, since it names
    every collection and counts its titles. There was briefly a second handler
    on this path doing only that: FastAPI matches the first one registered, so
    the second answered nothing and the setting would have been picked from a
    list nobody was serving.
    """
    from app.services import collections as service

    return service.health(db, problem_days=days)


@router.get("/overview")
def overview(_: AdminUser, db: Db) -> dict:
    from app.services.library_scan import in_library, last_scan

    playable = MediaItem.media_type.in_(("movie", "episode"))
    present = in_library()
    total = db.execute(select(func.count()).select_from(MediaItem).where(playable, MediaItem.title.is_not(None), present)).scalar() or 0
    checked = db.execute(
        select(func.count()).select_from(MediaItem).where(playable, MediaItem.file_checked_at.is_not(None), present)
    ).scalar() or 0
    size = db.execute(select(func.sum(MediaItem.file_size)).where(playable, present)).scalar() or 0
    scanned = last_scan()
    resolutions = db.execute(
        select(MediaItem.video_resolution, func.count(), func.sum(MediaItem.file_size))
        .where(MediaItem.file_bitrate.is_not(None), playable, present)
        .group_by(MediaItem.video_resolution)
        .order_by(func.count().desc())
    ).all()
    return {
        "titles": total,
        "scanned_at": scanned.isoformat() if scanned else None,
        "checked": checked,
        "size": size,
        "threshold_mbps": current().library_bitrate_threshold_mbps,
        "streams_recorded": db.execute(select(func.count()).select_from(StreamSession)).scalar() or 0,
        "stalls_recorded": db.execute(select(func.count()).select_from(StreamEvent)).scalar() or 0,
        "resolutions": [{"resolution": r or "Unknown", "files": n, "size": s or 0} for r, n, s in resolutions],
    }


@router.get("/space")
def space(_: AdminUser, db: Db) -> dict:
    """What each library takes, what it has gained or lost, and what is left
    on the disks it sits on."""
    from app.services import space as space_service

    return space_service.report(db)


@router.get("/shows")
def shows(_: AdminUser, db: Db, days: int = Days, section_id: int | None = None,
          search: str | None = None, store: list[str] | None = Query(None),
          sort: str = "title") -> dict:
    """Every show, built from its episodes."""
    return library.shows(db, days, section_id=section_id, search=search, stores=store, sort=sort)


@router.get("/shows/{show_key}")
def show_seasons(show_key: int, _: AdminUser, db: Db, days: int = Days) -> dict:
    """One show's seasons."""
    return library.seasons(db, show_key, days)


@router.get("/transcodes")
def transcodes(_: AdminUser, db: Db, days: int = Days) -> dict:
    return library.transcode_causes(db, days)


@router.get("/four-k")
def four_k(_: AdminUser, db: Db, days: int = Query(365, ge=1, le=3650)) -> list:
    return library.four_k(db, days)


_requests_cache: dict[str, object] = {"at": 0.0, "value": None}


@router.get("/requests")
async def requests(_: AdminUser, fresh: bool = False) -> dict:
    import asyncio
    import time

    if not fresh and _requests_cache["value"] is not None and time.time() - float(_requests_cache["at"]) < 600:
        return _requests_cache["value"]  # type: ignore[return-value]
    try:
        value = await asyncio.wait_for(library.unwatched_requests(), timeout=90)
    except TimeoutError as exc:
        raise HTTPException(504, "Seerr took longer than 90 seconds to list its requests.") from exc
    except Exception as exc:  # noqa: BLE001
        from app.integrations.base import describe_failure

        raise HTTPException(502, f"Seerr: {describe_failure(exc)}") from exc
    _requests_cache["at"], _requests_cache["value"] = time.time(), value
    return value


def _file_payload(rating_key: int, days: int) -> dict | None:
    """Everything about one file from the database. Run in a worker thread."""
    from app.db import session_scope
    from app.services.library import _since

    since, cutoff = _since(days)
    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None or item.title is None:
            return None
        stats = library.play_stats(db, days, [rating_key]).get(rating_key, {})
        platforms = [
            {"platform": name or "Unknown", "plays": n, "transcodes": int(t or 0)}
            for name, n, t in db.execute(
                select(History.platform, func.count(), func.sum(case((History.transcode_decision == "transcode", 1), else_=0)))
                .where(History.rating_key == rating_key, History.started >= since)
                .group_by(History.platform)
                .order_by(func.count().desc())
            ).all()
        ]
        stalls = db.execute(
            select(StreamEvent.cause, func.count())
            .where(StreamEvent.rating_key == rating_key, StreamEvent.started_at >= cutoff)
            .group_by(StreamEvent.cause)
        ).all()
        causes = db.execute(
            select(StreamSession.primary_cause, func.count())
            .where(StreamSession.rating_key == rating_key, StreamSession.primary_cause.is_not(None),
                   StreamSession.started_at >= cutoff)
            .group_by(StreamSession.primary_cause)
        ).all()
        # The latest transcoded plays, so their reasons can be read from
        # Tautulli when live recording did not see them.
        transcoded_rows = [
            row_id
            for (row_id,) in db.execute(
                select(History.row_id)
                .where(History.rating_key == rating_key, History.transcode_decision == "transcode", History.started >= since)
                .order_by(History.started.desc())
                .limit(3)
            ).all()
        ]
        from app.services import stores as store_service

        return {
            **library.describe_file(item),
            "media_type": item.media_type,
            "store": store_service.name_for(item.file_path),
            "plays": int(stats.get("plays") or 0),
            "remote_plays": int(stats.get("remote") or 0),
            "transcodes": int(stats.get("transcodes") or 0),
            "users": int(stats.get("users") or 0),
            "last_play": stats.get("last_play"),
            "platforms": platforms,
            "stall_causes": [{"cause": c or "one_off", "stalls": n} for c, n in stalls],
            "transcode_causes": [{"cause": c, "streams": n} for c, n in causes],
            "_transcoded_rows": transcoded_rows,
        }


async def _causes_from_history(row_ids: list[int]) -> list[dict]:
    """Why earlier plays transcoded, from Tautulli's per-play stream details.
    Best effort: a slow or missing answer just leaves the reason unknown."""
    import asyncio
    from collections import Counter

    from app.services.streams import transcode_causes
    from app.settings_store import tautulli_configured
    from app.tautulli.client import TautulliClient

    # The stream detail of a past play is only Tautulli's to give, and only
    # for its own plays: a negative id is one recorded here from Plex.
    row_ids = [r for r in row_ids if r > 0]
    if not row_ids or not tautulli_configured():
        return []
    client = TautulliClient(current())
    counts: Counter = Counter()
    try:
        for row_id in row_ids:
            try:
                data = await asyncio.wait_for(client.call("get_stream_data", row_id=row_id), timeout=10)
            except Exception:  # noqa: BLE001
                continue
            for cause in transcode_causes(data or {}):
                counts[cause] += 1
    finally:
        await client.aclose()
    return [{"cause": c, "streams": n, "from_history": True} for c, n in counts.items()]


@router.get("/stalls/unfiltered")
def old_stalls(db: Db, _: AdminUser) -> dict:
    """Stalls recorded before skipping and episode endings were told apart
    from buffering. They cannot be sorted out now, only kept or forgotten."""
    from app.services import stalls

    count, newest = stalls.unfiltered(db)
    return {
        "count": count,
        "newest": newest.isoformat() if newest else None,
        "since": stalls.SEEK_FILTERING_SINCE.date().isoformat(),
    }


@router.delete("/stalls/unfiltered")
def forget_old_stalls(db: Db, admin: AdminUser) -> dict:
    from app.services import stalls

    count = stalls.forget_unfiltered(db)
    db.commit()
    audit.record(admin, "library.stalls_forgotten", f"Forgot {count} stalls recorded before skips were excluded")
    return {"forgotten": count}


@router.get("/attention")
async def attention(_: AdminUser, kind: str = Query("trouble", pattern="^(trouble|messy|room)$"), days: int = Days) -> dict:
    """Files worth doing something about, asked three ways.

    Trouble for the people watching, awkward to play, or taking up room. One
    list, because the answer to all three is the same: look at the file, ask
    for a better copy, or decide to keep it.
    """
    import asyncio

    from app.services import cleanup

    threshold = int(current().library_bitrate_threshold_mbps * 1000)
    return await asyncio.to_thread(cleanup.attention, kind, days, threshold)


@router.get("/gaps")
def gaps(_: AdminUser, db: Db, section_id: int | None = None) -> dict:
    """Seasons with an episode missing out of the middle of them.

    Only the middle. A season that has aired five of ten has no hole in it,
    and an app that calls that five missing episodes is wrong every week of
    every season.
    """
    from app.services import gaps as service

    return service.holes(db, section_id)


@router.get("/copies")
async def copies(_: AdminUser, section_id: int | None = None, sizes: bool = True) -> dict:
    """What the library is holding twice.

    Two different things under one question, because the answer to both is the
    same: an item Plex has several files for, and two separate items that
    claim to be the same title.

    Sizes come from Plex because they are not kept: a worker thread, since the
    page waits on it and plexapi blocks.
    """
    import asyncio

    from app.services import gaps as service

    def read() -> dict:
        with session_scope() as db:
            return service.copies(db, section_id, sizes=sizes)

    return await asyncio.to_thread(read)


@router.get("/cleanup")
async def cleanup(_: AdminUser, days: int = Days) -> dict:
    """Big files nobody watches, and why each one stands out."""
    import asyncio

    from app.services import cleanup as service

    return await asyncio.to_thread(service.candidates, days)


@router.get("/cleanup/kept")
def kept(_: AdminUser) -> list[dict]:
    from app.services import cleanup as service

    return service.kept_list()


@router.post("/cleanup/{rating_key}/keep")
def keep_file(rating_key: int, admin: AdminUser, reason: str = Body("", embed=True)) -> dict:
    from app.services import cleanup as service

    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        title = (item.full_title or item.title) if item else f"item {rating_key}"
    service.keep(rating_key, admin.username, reason)
    audit.record(admin, "library.keep", f"Decided to keep {title}", target=str(rating_key),
                 detail={"reason": {"after": reason or None}})
    return {"rating_key": rating_key, "kept": True}


@router.delete("/cleanup/{rating_key}/keep")
def unkeep_file(rating_key: int, admin: AdminUser) -> dict:
    from app.services import cleanup as service

    if not service.unkeep(rating_key):
        raise HTTPException(404, "That one was not on the keep list")
    audit.record(admin, "library.keep_undone", f"Put {rating_key} back in the review", target=str(rating_key))
    return {"rating_key": rating_key, "kept": False}


async def _move_target(rating_key: int):
    """The title as the service holds it, and the service holding it.

    Reuses the lookup that finds a title by the id Plex matched it to and then
    by IMDb, so a wrong match says which id it looked for here too rather than
    failing as "not in Radarr" about a film plainly sitting in Radarr.
    """
    from app.integrations.base import get_json

    target, service = await _arr_target(rating_key)
    try:
        found, _episode = await service.locate(
            target["external"], target["season"], target["episode"], target.get("alt")
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    # The whole resource, because the move hands it back and the service
    # expects every field it gave.
    whole = await get_json(f"{service.base_url}/api/v3/{service.path}/{found['id']}", headers=service.headers)
    if not whole:
        raise HTTPException(502, f"{service.label} would not describe that title")
    return whole, service


@router.get("/file/{rating_key}/move")
async def move_options(rating_key: int, _: AdminUser, to: str | None = None) -> dict:
    """Where this title could go, and what moving it there would do.

    Nothing is changed by asking. The plan is also run again when the move is
    asked for, because a plan somebody read for two minutes is a plan about
    the past.
    """
    from app.services import moves

    whole, service = await _move_target(rating_key)
    where = await moves.destinations(service)
    plan = await moves.plan(service, rating_key, whole, to) if to else None
    return {
        "service": service.label,
        "title": whole.get("title"),
        "here": (whole.get("rootFolderPath") or "").rstrip("/") or None,
        "bytes": moves.size_of(whole),
        # One path per series, so asking about an episode moves the show.
        "whole_show": moves.is_a_show(whole),
        "destinations": where,
        # Said rather than implied: it is the service's own reading of each
        # share, and a share that over reports fools it as it fools everything.
        "free_is_from": service.label,
        "plan": plan,
    }


@router.post("/file/{rating_key}/move")
async def move_file(rating_key: int, admin: AdminUser, to: str = Body(..., embed=True)) -> dict:
    """Ask the service to move it, and tell Plex about both folders."""
    from app import audit
    from app.integrations.base import describe_failure
    from app.services import moves

    # Through the queue, like every other move.
    #
    # This used to ask the service there and then and record nothing, so a
    # move made from a title's own card left no trace: the queue showed
    # nothing, there was no way to see whether it had finished, and a move
    # that silently did not happen looked exactly like one that had. One path
    # means one record, one thing watching it, and one place to look.
    import asyncio

    whole, service = await _move_target(rating_key)
    job = await asyncio.to_thread(
        moves.queue, rating_key, service.name, whole.get("id"), whole.get("title"),
        to, (whole.get("rootFolderPath") or "").rstrip("/") or None,
        moves.size_of(whole), admin.username,
    )
    moves.start_worker()
    audit.record(
        admin, "library.move",
        f"Queued a move of {whole.get('title')} to {to}", target=str(rating_key),
    )
    return job


@router.get("/moves")
def move_queue(_: AdminUser, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    """What is queued to move, moving, or lately moved."""
    from app.services import moves

    return moves.listing(limit)


@router.post("/moves")
async def queue_move(
    admin: AdminUser,
    rating_key: int = Body(..., embed=True),
    to: str = Body(..., embed=True),
) -> dict:
    """Put one title in the move queue.

    Nothing is checked against the service here beyond finding the title:
    whether it can move is asked when its turn comes, because by then the
    answer may be different, and a queue somebody fills in one sitting is
    mostly a list of things that cannot move for another hour yet.
    """
    import asyncio

    from app import audit
    from app.services import moves

    whole, service = await _move_target(rating_key)
    job = await asyncio.to_thread(
        moves.queue, rating_key, service.name, whole.get("id"), whole.get("title"),
        to, (whole.get("rootFolderPath") or "").rstrip("/") or None,
        moves.size_of(whole), admin.username,
    )
    moves.start_worker()
    audit.record(admin, "library.move.queue",
                 f"Queued a move of {whole.get('title')} to {to}", target=str(rating_key))
    return job


@router.delete("/moves/{job_id}")
def unqueue_move(job_id: int, admin: AdminUser) -> dict:
    """Take one out of the queue. One already moving is left to the service."""
    from app import audit
    from app.services import moves

    if not moves.cancel(job_id):
        raise HTTPException(409, "That one is not waiting any more")
    audit.record(admin, "library.move.cancel", f"Took move {job_id} out of the queue")
    return {"ok": True}


@router.get("/stores")
async def stores(_: AdminUser, days: int = Query(30, ge=1, le=3650)) -> dict:
    """Each storage mount: what it holds, and what goes wrong watching from it."""
    import asyncio

    from app.services import stores as store_service

    return await asyncio.to_thread(store_service.summary, days)


@router.get("/stores/trend")
async def stores_trend(_: AdminUser, weeks: int = Query(12, ge=2, le=52)) -> dict:
    """How often watching from each store went wrong, week by week."""
    import asyncio

    from app.services import stores as store_service

    return await asyncio.to_thread(store_service.trend, weeks)


@router.get("/bitrate-advice")
async def bitrate_advice(_: AdminUser, days: int = Query(90, ge=7, le=3650)) -> dict:
    """What the problem bitrate threshold could be, read from remote streams."""
    import asyncio

    from app.services import streams

    return await asyncio.to_thread(streams.bitrate_advice, days)


# ---- files that are large for what they are ---------------------------------


@router.get("/big")
async def big_files(
    _: AdminUser,
    days: int = Query(90, ge=1, le=3650),
    min_gb_per_hour: float = Query(0, ge=0, le=100),
    min_bitrate_kbps: int = Query(0, ge=0, le=500_000),
    resolution: str | None = None,
    section_id: int | None = None,
    language: str | None = None,
    media_type: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Biggest per hour first, with what it would take to narrow the list."""
    import asyncio

    from app.services import library

    def look():
        with session_scope() as db:
            return library.oversized(
                db, days, min_gb_per_hour=min_gb_per_hour, min_bitrate_kbps=min_bitrate_kbps,
                resolution=resolution, section_id=section_id, language=language,
                media_type=media_type, limit=limit,
            )

    return await asyncio.to_thread(look)


@router.get("/browse")
async def browse_library(
    _: AdminUser,
    days: int = Query(90, ge=1, le=3650),
    sort: str = "per_hour",
    min_gb_per_hour: float = Query(0, ge=0, le=100),
    min_bitrate_kbps: int = Query(0, ge=0, le=500_000),
    resolution: str | None = None,
    section_id: int | None = None,
    language: str | None = None,
    media_type: str | None = "movie",
    problem: str | None = None,
    search: str | None = None,
    show: int | None = None,
    season: int | None = None,
    store: list[str] | None = Query(None),
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0, le=100_000),
) -> dict:
    """The library as something to look through, sorted by what is wrong."""
    import asyncio

    from app.services import library

    def look():
        with session_scope() as db:
            return library.browse(
                db, days, sort=sort, min_gb_per_hour=min_gb_per_hour, min_bitrate_kbps=min_bitrate_kbps,
                resolution=resolution, section_id=section_id, language=language, media_type=media_type,
                problem=problem, search=search, show=show, season=season, stores=store,
                limit=limit, offset=offset,
            )

    return await asyncio.to_thread(look)


TAG_CAP = 100
"""Most that one press may tag. A filter that matches two thousand files is a
filter to narrow, not a button to press."""


@router.post("/big/tag")
async def tag_big_files(admin: AdminUser, keys: list[int] = Body(..., embed=True)) -> dict:
    """Tag these in Radarr or Sonarr, to pick replacements by hand later.

    Nothing is downloaded and nothing is deleted: the tag is a shortlist that
    survives leaving this page.
    """
    from app.integrations.base import describe_failure

    if not keys:
        raise HTTPException(400, "Nothing chosen")
    if len(keys) > TAG_CAP:
        raise HTTPException(400, f"That is {len(keys)} files. Narrow the filters, or tag {TAG_CAP} at a time.")

    tagged, failed = [], []
    for key in keys:
        try:
            target, service = await _arr_target(key)
            found, _episode = await service.locate(
                target["external"], target["season"], target["episode"], target.get("alt")
            )
            await service.tag(found["id"])
            tagged.append(key)
        except HTTPException as exc:
            failed.append({"rating_key": key, "why": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001 - one title missing must not stop the rest
            failed.append({"rating_key": key, "why": describe_failure(exc)})

    audit.record(admin, "library.tag.bulk", f"Tagged {len(tagged)} large files for replacement")
    return {"tagged": len(tagged), "failed": failed}


# ---- tidying a file's tracks -------------------------------------------------


PER_LIBRARY = 4
"""Extra files fetched for each library, so none of them is judged on one
path that happens to have been deleted since the scan read it."""


DIRECTORY_CAP = 500
"""Enough to list a crowded share, few enough that a wrong turn into a folder
of ten thousand episodes does not hang the box."""


@router.get("/tidy/status")
async def tidy_status(_: AdminUser, sample: int = Query(40, ge=1, le=500)) -> dict:
    """Whether this container can actually tidy anything, and why not.

    Answers the two questions by looking rather than by explaining: is ffmpeg
    here, and can the paths Plex reports be opened from inside this container.
    """
    import asyncio

    from app.models import MediaItem
    from app.services import mediafix

    def look():
        with session_scope() as db:
            paths = [
                row[0]
                for row in db.execute(
                    select(MediaItem.file_path)
                    .where(MediaItem.file_path.is_not(None))
                    .order_by(MediaItem.rating_key.desc())
                    .limit(sample)
                ).all()
            ]
            # The newest files in one library can be a single row of a shared
            # sample, and one stale path is then the whole library's answer. So
            # each library gets a few of its own, taken from the far end of the
            # list where nothing has been touched lately.
            for library in sorted({mediafix.library_of(path) for path in paths}):
                paths.extend(
                    row[0]
                    for row in db.execute(
                        select(MediaItem.file_path)
                        .where(MediaItem.file_path.like(f"{library}/%"))
                        .order_by(MediaItem.rating_key.asc())
                        .limit(PER_LIBRARY)
                    ).all()
                )

        seen = [path for path in paths if mediafix.local_path(path)]
        missing = [path for path in paths if path not in set(seen)]
        return {
            "checked": len(paths),
            "visible": len(seen),
            # A row per library rather than a list of paths, because what a
            # person has to decide is per library: this one is found, that one
            # needs a mount or a mapping.
            "libraries": mediafix.where_libraries(paths),
            "missing_roots": sorted({mediafix.library_of(path) for path in missing})[:10],
            "example": missing[0] if missing else None,
        }

    answer = await asyncio.to_thread(look)
    answer["tools"] = await asyncio.to_thread(mediafix.tools)
    answer["path_map"] = mediafix.path_map()
    answer["roots"] = mediafix.roots()
    # What is actually inside each mount, which is the one thing nobody can see
    # from outside the container and the first thing worth knowing.
    answer["root_status"] = await asyncio.to_thread(mediafix.root_status)
    return answer


@router.get("/tidy/directories")
async def tidy_directories(_: AdminUser, path: str = Query("/")) -> dict:
    """What this container can see at a path, one level down.

    Setting a mount means knowing what was actually mounted, which is a
    question only the container can answer. Directory names and nothing else:
    no files, no sizes, no contents. Admin only, like everything else here.
    """
    import asyncio
    import os

    def look() -> dict:
        here = os.path.abspath(path or "/")
        # A half typed path lists the directory it is inside, which is what
        # makes completion work while somebody is still typing.
        if not os.path.isdir(here):
            here = os.path.dirname(here) or "/"

        names: list[str] = []
        problem = None
        try:
            with os.scandir(here) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    try:
                        if not entry.is_dir():
                            continue
                    except OSError:
                        continue
                    names.append(entry.name)
                    if len(names) >= DIRECTORY_CAP:
                        break
        except OSError as err:
            problem = err.strerror or str(err)

        names.sort(key=str.lower)
        shown = here.replace("\\", "/")
        if len(shown) > 1:
            shown = shown.rstrip("/")
        parent = os.path.dirname(here).replace("\\", "/") or "/"
        return {
            "path": shown,
            "parent": parent if parent != shown else None,
            "directories": [
                {"name": name, "path": f"{shown.rstrip('/')}/{name}"} for name in names
            ],
            "error": problem,
        }

    return await asyncio.to_thread(look)


@router.get("/file/{rating_key}/tidy")
async def tidy_plan(rating_key: int, _: AdminUser) -> dict:
    """What tidying this file would do, and whether this container can."""
    import asyncio

    from app.models import MediaItem
    from app.services import mediafix

    def look():
        with session_scope() as db:
            item = db.get(MediaItem, rating_key)
            if item is None or item.title is None:
                return None
            answer = mediafix.plan(item)
            answer["local_path"] = mediafix.local_path(item.file_path)
            return answer

    answer = await asyncio.to_thread(look)
    if answer is None:
        raise HTTPException(404, "No such title")
    answer["tools"] = await asyncio.to_thread(mediafix.tools)
    return answer


@router.post("/file/{rating_key}/tidy")
async def tidy_file(
    rating_key: int,
    admin: AdminUser,
    steps: list[str] = Body(default_factory=list, embed=True),
    chosen: dict = Body(default_factory=dict, embed=True),
) -> dict:
    """Queue the tidying. One file is worked on at a time.

    `chosen` is a choice made on the file itself: which audio and subtitle
    tracks to keep, counted within their own kind, and which audio track goes
    first. It wins over anything worked out from Settings, because somebody is
    looking at the actual track list.
    """
    import asyncio

    from app import audit
    from app.services import mediafix

    try:
        job_id = await asyncio.to_thread(mediafix.queue, rating_key, steps, admin.username, chosen or None)
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    mediafix.start_worker()
    audit.record(admin, "library.tidy.queued", f"Queued tidying for {rating_key}: {', '.join(steps)}",
                 target=str(rating_key))
    return {"job": job_id}


MANY_CAP = 200
"""The most files one bulk tidy will touch.

This rewrites whole films, and a mistake at four hundred files is a different
kind of mistake from one at ten. An attention list is cut to this and asked
again for the next lot, since it is ordered worst first and the first two
hundred are the two hundred worth doing. A collection is not ordered by
anything of the sort, so one over the cap is refused by name instead of
quietly becoming its first two hundred titles.
"""


def _collection_rows(name: str) -> list[dict]:
    """Every file in a collection, or the reason it cannot be tidied."""
    from app.services import collections as collections_service

    with session_scope() as db:
        if not collections_service.exists(db, name):
            raise HTTPException(404, f"No collection called {name!r}. They are read from Plex by the library scan.")
        rows = collections_service.members(db, name)
    if len(rows) > MANY_CAP:
        raise HTTPException(
            400,
            f"{name} holds {len(rows):,} files, more than the {MANY_CAP} one tidy will touch. "
            "Tidy these from the Messy files list, which puts the worst first, "
            "or split the collection in Plex.",
        )
    if not rows:
        raise HTTPException(404, f"{name} holds nothing the library still has.")
    return rows


@router.post("/tidy/many")
async def tidy_many(
    admin: AdminUser,
    kind: str = Body("messy", embed=True),
    collection: str | None = Body(None, embed=True),
    days: int = Body(365, embed=True),
    limit: int = Body(50, embed=True),
    dry_run: bool = Body(False, embed=True),
) -> dict:
    """Queue every file in one of the attention lists, or in one collection.

    Each file gets its own job with its own steps, worked out from that file
    rather than from a rule applied to all of them: a file with styled
    subtitles and a file with twenty duplicates do not want the same thing
    done to them. That is what makes a collection a sensible thing to hand
    this: a collection is a list of titles somebody wrote down, not a list of
    files with one fault in common.

    `collection` names one and wins over `kind`, which has a default and so
    cannot be told apart from an unasked question. Everything past working out
    the keys is the same either way.
    """
    import asyncio

    from app import audit
    from app.services import cleanup as cleanup_service
    from app.services import mediafix

    if collection:
        rows = await asyncio.to_thread(_collection_rows, collection)
        source = f"the {collection} collection"
    else:
        if kind not in ("messy", "trouble"):
            raise HTTPException(400, "That list cannot be tidied")
        limit = max(1, min(limit, MANY_CAP))

        found = await asyncio.to_thread(
            cleanup_service.attention, kind, days, current().library_bitrate_threshold_mbps * 1000, limit
        )
        rows = found.get("items", [])
        source = kind

    def plan_for(rating_key: int) -> tuple[list[str], int | None]:
        """The steps for one file, and what they would come to in bytes.

        None for the size where any step could not say, which is about one
        file in ten: a total missing a term is not a total, and the answer the
        list gives has to say when it is a floor rather than quietly
        understating itself.
        """
        with session_scope() as db:
            item = db.get(MediaItem, rating_key)
            if item is None:
                return [], 0
            steps = mediafix.plan(item)["steps"]
            changes = [step.get("size_change") for step in steps]
            total = None if any(c is None for c in changes) else sum(c or 0 for c in changes)
            return [step["key"] for step in steps], total

    queued, skipped = [], []
    # Negative is smaller, the same sign one file uses, so the two agree.
    total_bytes = 0
    unknown = 0
    for row in rows:
        key = row.get("rating_key")
        if key is None:
            continue
        steps, size_change = await asyncio.to_thread(plan_for, key)
        if not steps:
            skipped.append({"rating_key": key, "title": row.get("title"), "why": "nothing to do to it"})
            continue
        # Counted here, past the files with nothing to do to them: what a
        # file nobody is going to touch would have come to is not part of
        # the answer.
        if size_change is None:
            unknown += 1
        else:
            total_bytes += size_change
        if dry_run:
            queued.append({
                "rating_key": key, "title": row.get("title"), "steps": steps, "size_change": size_change,
            })
            continue
        try:
            job = await asyncio.to_thread(mediafix.queue, key, steps, admin.username, None)
        except (LookupError, ValueError) as exc:
            skipped.append({"rating_key": key, "title": row.get("title"), "why": str(exc)})
            continue
        queued.append({"rating_key": key, "title": row.get("title"), "steps": steps, "job": job})

    if queued and not dry_run:
        mediafix.start_worker()
        audit.record(
            admin, "library.tidy.many",
            f"Queued tidying for {len(queued)} files from {source}",
            detail={
                "queued": len(queued), "skipped": len(skipped),
                "kind": None if collection else kind, "collection": collection,
            },
        )
    return {
        "queued": len(queued),
        "skipped": len(skipped),
        "files": queued[:200],
        "not_done": skipped[:50],
        "dry_run": dry_run,
        # Which lot this was, so the answer stands on its own in the log.
        "collection": collection,
        # What the whole lot would come to. Counted over the files that would
        # actually be queued, since one with nothing to do to it changes
        # nothing either way.
        "size_change": total_bytes,
        "size_unknown": unknown,
    }


@router.get("/tidy/jobs")
def tidy_jobs(_: AdminUser, db: Db, limit: int = Query(20, ge=1, le=200)) -> list[dict]:
    import json as json_module

    from app.models import MediaJob

    def keys(job: MediaJob) -> list[str]:
        """The step keys, whichever shape the job was stored in.

        Jobs from before track picking held a bare list; newer ones hold the
        list beside the tracks chosen on the file itself.
        """
        asked = json_module.loads(job.steps or "[]")
        return asked.get("steps", []) if isinstance(asked, dict) else asked

    rows = db.execute(select(MediaJob).order_by(MediaJob.id.desc()).limit(limit)).scalars().all()
    return [
        {
            **{c.name: getattr(job, c.name) for c in MediaJob.__table__.columns},
            "steps": keys(job),
        }
        for job in rows
    ]


@router.post("/tidy/jobs/{job_id}/cancel")
def cancel_tidy(job_id: int, admin: AdminUser) -> dict:
    from app import audit
    from app.services import mediafix

    if not mediafix.cancel(job_id):
        raise HTTPException(404, "Nothing to stop")
    audit.record(admin, "library.tidy.cancelled", f"Stopped tidying job {job_id}", target=str(job_id))
    return {"cancelled": job_id}


@router.get("/stores/trouble")
async def store_trouble(
    _: AdminUser, store: str = Query(..., min_length=1), days: int = Query(30, ge=1, le=3650)
) -> dict:
    """What the stalling at one store is made of: who, what, and from where."""
    import asyncio

    from app.services import stores as store_service

    return await asyncio.to_thread(store_service.trouble, store, days)


@router.put("/stores/{prefix:path}")
def name_store(prefix: str, admin: AdminUser, label: str = Body("", embed=True)) -> dict:
    """Name a mount. Two mounts with the same name are one store, which is how
    several shares off one box are read together."""
    from app.services import stores as store_service

    prefix = "/" + prefix.strip("/")
    known = {root for store in store_service.summary(1)["stores"] for root in store["roots"]}
    if prefix not in known:
        raise HTTPException(404, "No files are stored there")
    store_service.rename(prefix, label.strip())
    audit.record(admin, "library.store", f"Called {prefix} {label.strip() or prefix}", target=prefix)
    return {"prefix": prefix, "label": label.strip()}


@router.get("/file/{rating_key}")
async def file(rating_key: int, _: AdminUser, days: int = Query(365, ge=1, le=3650)) -> dict:
    import asyncio

    from app.integrations import arr as arr_integrations
    from app.services import findings

    payload = await asyncio.to_thread(_file_payload, rating_key, days)
    if payload is None:
        raise HTTPException(404, "No such title")
    rows = payload.pop("_transcoded_rows")
    if not payload["transcode_causes"] and rows:
        payload["transcode_causes"] = await _causes_from_history(rows)
    service = arr_integrations.for_media_type(payload["media_type"])
    payload["findings"] = findings.explain(
        payload,
        int(current().library_bitrate_threshold_mbps * 1000),
        payload["transcode_causes"],
        payload["stall_causes"],
        service.label,
    )
    payload["arr"] = {"name": service.name, "label": service.label, "configured": service.configured()}
    return payload


@router.post("/file/{rating_key}/arr")
async def replace_file(rating_key: int, admin: AdminUser, action: str = Body(..., embed=True)) -> dict:
    """Hand a file back to Radarr or Sonarr: search for a replacement, or tag
    it. Nothing is deleted."""
    import asyncio

    from app import audit
    from app.db import session_scope
    from app.integrations import arr as arr_integrations
    from app.integrations.base import describe_failure
    from app.redact import redact

    if action not in ("search", "tag"):
        raise HTTPException(400, "Action is search or tag")
    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None or item.title is None:
            raise HTTPException(404, "No such title")
        service = arr_integrations.for_media_type(item.media_type)
        episodic = item.media_type == "episode"
        show_key = item.grandparent_rating_key
        show = db.get(MediaItem, show_key) if episodic and show_key else None
        if episodic:
            external = show.tvdb_id if show else None
            alt = show.imdb_id if show else None
        else:
            external = item.tmdb_id if service.name == "radarr" else item.tvdb_id
            alt = item.imdb_id
        title = library._title(item)
        season, episode = item.parent_media_index, item.media_index
    if not service.configured():
        raise HTTPException(409, f"Connect {service.label} in Settings first")
    if episodic and not external and show_key:
        from app.services.sync import cache_one

        await cache_one(show_key)
        with session_scope() as db:
            show = db.get(MediaItem, show_key)
            external = show.tvdb_id if show else None
    if not external:
        kind = "TMDB" if service.name == "radarr" else "TVDB"
        raise HTTPException(409, f"No {kind} id for this title, so {service.label} cannot find it")
    try:
        if action == "search":
            result = await asyncio.wait_for(service.search(external, season, episode, alt), timeout=45)
        else:
            result = await asyncio.wait_for(service.tag(external), timeout=45)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        audit.record(admin, f"library.{action}", f"Tried to hand {title} to {service.label}", target=str(rating_key),
                     result=f"failed: {redact(exc)}")
        raise HTTPException(502, f"{service.label}: {describe_failure(exc)}") from exc
    audit.record(admin, f"library.{action}", result, target=str(rating_key))
    return {"ok": True, "message": result}


@router.get("/file/{rating_key}/match")
async def match_candidates(rating_key: int, _: AdminUser) -> dict:
    """What Plex says this item could be, for somebody to choose from.

    Read only. The answer is Plex's own Fix Match list, which is the one place
    a wrong match can be put right, and until now meant leaving the app.
    """
    import asyncio

    from app.plex import rematch
    from app.plex.server import NotConfigured
    from app.redact import redact

    try:
        return await asyncio.to_thread(rematch.candidates, rating_key)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except NotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - the server not answering is the answer
        raise HTTPException(502, f"Plex would not say what this could be: {redact(exc)}") from exc


@router.post("/file/{rating_key}/match")
async def fix_match(rating_key: int, admin: AdminUser, guid: str = Body(..., embed=True)) -> dict:
    """Match this item to one of the candidates Plex offered.

    A real change to somebody's server, so it is confirmed in the browser
    before it gets here, written to the log like the other Plex writes, and
    the app's own row is made to agree rather than left saying what the old
    match said.
    """
    import asyncio

    from app.plex import rematch
    from app.plex.server import NotConfigured
    from app.redact import redact

    try:
        done = await asyncio.to_thread(rematch.apply, rating_key, guid)
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc
    except NotConfigured as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        audit.record(admin, "library.match", f"Tried to re-match {rating_key}", target=str(rating_key),
                     result=f"failed: {redact(exc)}")
        raise HTTPException(502, f"Plex would not take that match: {redact(exc)}") from exc
    named = done.get("name") or done["guid"]
    audit.record(
        admin, "library.match",
        f"Matched {done.get('title') or done['rating_key']} to {named}"
        + (f" ({done['year']})" if done.get("year") else ""),
        target=str(done["rating_key"]),
        detail={"was": done.get("was_guid"), "now": done["guid"], "asked_about": done.get("asked_about"),
                "changed": done.get("changed")},
    )
    return {"ok": True, **done}


def _capacity():
    from app.services.streams import upload_capacity

    return upload_capacity()


@router.get("/upload")
def upload_settings(_: AdminUser) -> dict:
    """What upload Cartographarr measures against, for the Settings page."""
    from app.services.streams import plex_upload, upload_capacity

    total, per_stream = plex_upload()
    capacity, source = upload_capacity()
    return {
        "capacity_mbps": capacity or None,
        "source": source,
        "plex_upload_mbps": None if total is None else total / 1000,
        "plex_stream_limit_mbps": None if per_stream is None else per_stream / 1000,
    }


@router.get("/health")
def health_summary(_: AdminUser, db: Db) -> dict:
    """The dashboard's server health cards: stalls and what causes them,
    upload, how much transcodes, and who has stopped watching."""
    from datetime import UTC, datetime, timedelta

    from app.models import BandwidthSample, User
    from app.services.stalls import CAUSES as STALL_CAUSES

    now = datetime.now(UTC)
    week = now - timedelta(days=7)
    stall_rows = db.execute(
        select(StreamEvent.cause, func.count()).where(StreamEvent.started_at >= week).group_by(StreamEvent.cause)
    ).all()
    stalls = sum(n for _, n in stall_rows)
    top = max(stall_rows, key=lambda r: r[1]) if stall_rows else None
    peak = db.execute(
        select(func.max(BandwidthSample.wan_kbps)).where(BandwidthSample.minute >= int((now - timedelta(days=1)).timestamp()))
    ).scalar()
    streams, transcoded = db.execute(
        select(func.count(), func.sum(case((StreamSession.transcode_decision == "transcode", 1), else_=0))).where(
            StreamSession.started_at >= week
        )
    ).one()
    idle_days = int(current().access_inactive_days or 90)
    cutoff = int((now - timedelta(days=idle_days)).timestamp())
    last_play = dict(db.execute(select(History.user_id, func.max(History.started)).group_by(History.user_id)).all())
    active_users = [u for (u,) in db.execute(select(User.user_id).where(User.deleted_in_tautulli.isnot(True))).all()]
    not_watching = sum(1 for u in active_users if (last_play.get(u) or 0) < cutoff)
    return {
        "stalls_week": stalls,
        "top_stall_cause": None if top is None else STALL_CAUSES.get(top[0] or "one_off", top[0]),
        "peak_upload_mbps": round((peak or 0) / 1000, 1) if peak is not None else None,
        "upload_capacity_mbps": _capacity()[0] or None,
        "upload_capacity_source": _capacity()[1],
        "streams_week": int(streams or 0),
        "transcoded_week": int(transcoded or 0),
        "not_watching": not_watching,
        "people": len(active_users),
        "idle_days": idle_days,
    }


# ---- replacements ------------------------------------------------------------------------------

async def _arr_target(rating_key: int):
    """The title, its service, its external id and episode numbers."""
    import asyncio

    from app.db import session_scope
    from app.integrations import arr as arr_integrations

    def load():
        with session_scope() as db:
            item = db.get(MediaItem, rating_key)
            if item is None or item.title is None:
                return None
            show = db.get(MediaItem, item.grandparent_rating_key) if item.media_type == "episode" and item.grandparent_rating_key else None
            return {
                "item": library.describe_file(item) | {"duration": item.duration},
                "media_type": item.media_type,
                "show_key": item.grandparent_rating_key,
                "external": (show.tvdb_id if show else None) if item.media_type == "episode" else item.tmdb_id,
                # A second id to try where the service will filter on one.
                # Plex and the library disagree about which film an id means
                # more often than either is simply absent, and for an episode
                # the id that matters is the show's.
                "alt": (show.imdb_id if show else None) if item.media_type == "episode" else item.imdb_id,
                "season": item.parent_media_index,
                "episode": item.media_index,
            }

    target = await asyncio.to_thread(load)
    if target is None:
        raise HTTPException(404, "No such title")
    service = arr_integrations.for_media_type(target["media_type"])
    if not service.configured():
        raise HTTPException(409, f"Connect {service.label} in Settings first")
    if target["media_type"] == "episode" and not target["external"] and target["show_key"]:
        from app.services.sync import cache_one

        await cache_one(target["show_key"])
        target = await asyncio.to_thread(load)
    if not target["external"]:
        raise HTTPException(409, f"No {'TMDB' if service.name == 'radarr' else 'TVDB'} id for this title")
    return target, service


@router.get("/file/{rating_key}/releases")
async def find_releases(rating_key: int, _: AdminUser) -> dict:
    """Releases that could replace this file, each compared with it."""
    import asyncio

    from app.integrations.base import describe_failure
    from app.services import replacements

    target, service = await _arr_target(rating_key)
    try:
        found, episode_id = await service.locate(
            target["external"], target["season"], target["episode"], target.get("alt")
        )
        raw = await asyncio.wait_for(service.releases(found["id"], episode_id), timeout=150)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(504, f"{service.label} took too long searching the indexers") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{service.label}: {describe_failure(exc)}") from exc
    detail = await file(rating_key, _, days=365)
    current_file = {**target["item"], "findings": detail["findings"]}
    return {
        "service": service.label,
        "current": current_file,
        "releases": replacements.compare_releases(
            raw, current_file, target["item"].get("duration"), int(current().library_bitrate_threshold_mbps * 1000)
        ),
    }


@router.post("/file/{rating_key}/replace")
async def queue_replacement(
    rating_key: int,
    admin: AdminUser,
    release: dict = Body(..., embed=True),
    auto_confirm: bool = Body(False, embed=True),
) -> dict:
    """Grab the chosen release and follow it."""
    import json
    from datetime import UTC, datetime

    from app import audit
    from app.db import session_scope
    from app.integrations.base import describe_failure
    from app.models import Replacement
    from app.services import replacements

    target, service = await _arr_target(rating_key)
    if not release.get("guid") or release.get("indexer_id") is None:
        raise HTTPException(400, "Pick a release")
    try:
        found, episode_id = await service.locate(
            target["external"], target["season"], target["episode"], target.get("alt")
        )
        existing = await service.current_file(found["id"], episode_id)
        await service.grab(release["guid"], int(release["indexer_id"]))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{service.label}: {describe_failure(exc)}") from exc
    now = datetime.now(UTC)
    with session_scope() as db:
        row = Replacement(
            rating_key=rating_key, title=target["item"]["title"], service=service.name, arr_id=found["id"],
            episode_id=episode_id, guid=release["guid"], indexer_id=int(release["indexer_id"]), status="queued",
            release=json.dumps(release), current=json.dumps({**target["item"], "arr_file_id": (existing or {}).get("id")}),
            auto_confirm=bool(auto_confirm),
            created_by=admin.username, created_at=now, updated_at=now,
        )
        db.add(row)
        db.flush()
        out = replacements.to_dict(row)
    audit.record(admin, "library.replace", f"Queued a replacement for {target['item']['title']}: {release.get('title')}",
                 target=str(rating_key))
    return out


@router.get("/replacements")
def list_replacements(_: AdminUser, db: Db) -> list:
    from app.models import Replacement
    from app.services import replacements

    rows = db.execute(select(Replacement).order_by(Replacement.updated_at.desc()).limit(200)).scalars().all()
    order = {"ready": 0, "importing": 1, "downloading": 2, "queued": 3}
    return sorted((replacements.to_dict(r) for r in rows), key=lambda r: order.get(r["status"], 9))


async def _decide(replacement_id: int, admin, confirm: bool) -> dict:
    import asyncio
    import json
    from datetime import UTC, datetime

    from app import audit
    from app.db import session_scope
    from app.integrations.base import describe_failure
    from app.models import Replacement
    from app.services import replacements

    def load():
        with session_scope() as db:
            row = db.get(Replacement, replacement_id)
            if row is not None:
                db.expunge(row)
            return row

    row = await asyncio.to_thread(load)
    if row is None:
        raise HTTPException(404, "No such replacement")
    service = replacements._service(row.service)
    if not service.configured():
        raise HTTPException(409, f"Connect {service.label} in Settings first")
    try:
        if confirm:
            if row.status != "ready":
                raise HTTPException(409, "It is not downloaded and waiting yet")
            biggest = replacements.importable(row.candidate)
            if biggest is None:
                raise HTTPException(409, f"{service.label} found no file to import in the download")
            await service.manual_import([biggest], row.arr_id, row.episode_id, row.download_id)
            status = "importing"
        else:
            if row.status not in ("queued", "downloading", "ready"):
                raise HTTPException(409, "Too late to deny this one")
            if row.queue_id is not None:
                await service.remove_from_queue(row.queue_id)
            status = "denied"
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{service.label}: {describe_failure(exc)}") from exc

    with session_scope() as db:
        stored = db.get(Replacement, replacement_id)
        stored.status, stored.resolved_by, stored.updated_at = status, admin.username, datetime.now(UTC)
        out = replacements.to_dict(stored)
    audit.record(
        admin, "library.replace_confirm" if confirm else "library.replace_deny",
        f"{'Confirmed' if confirm else 'Denied'} the replacement for {row.title}", target=str(row.rating_key),
    )
    return out


@router.get("/replacements/{replacement_id}/live")
async def replacement_live(replacement_id: int, _: AdminUser) -> dict:
    """This replacement as Radarr or Sonarr sees it right now: its queue entry
    and history. Also brings the stored status up to date."""
    import asyncio

    from app.db import session_scope
    from app.integrations.base import describe_failure
    from app.models import Replacement
    from app.services import replacements

    def load():
        with session_scope() as db:
            row = db.get(Replacement, replacement_id)
            if row is not None:
                db.expunge(row)
            return row

    row = await asyncio.to_thread(load)
    if row is None:
        raise HTTPException(404, "No such replacement")
    service = replacements._service(row.service)
    if not service.configured():
        raise HTTPException(409, f"Connect {service.label} in Settings first")
    try:
        shown, update = await replacements.live(row, service)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{service.label}: {describe_failure(exc)}") from exc
    await asyncio.to_thread(replacements.save, row, update)
    row = await asyncio.to_thread(load)
    return {**replacements.to_dict(row), "live": shown}


@router.post("/replacements/{replacement_id}/confirm")
async def confirm_replacement(replacement_id: int, admin: AdminUser) -> dict:
    return await _decide(replacement_id, admin, confirm=True)


@router.post("/replacements/{replacement_id}/deny")
async def deny_replacement(replacement_id: int, admin: AdminUser) -> dict:
    return await _decide(replacement_id, admin, confirm=False)
