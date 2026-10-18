"""Moving a title from one library source to another.

An array fills up and the answer is to move things off it. Doing that by hand
means moving the files, then telling Radarr where they went, then telling Plex,
and getting any of the three wrong leaves a library that half knows where its
own files are.

So the service does it. Radarr and Sonarr each move the files and update their
own record in one operation, which nothing outside them can do correctly, and
this asks for that and then tells Plex about both folders. The app never moves
a file itself: it has no way to keep the service's database honest afterwards.

What was measured against a real Radarr 6.4.4 before any of this was written:

- `GET /api/v3/rootfolder` gives id, path, accessible, freeSpace and
  unmappedFolders, and nothing else. Six roots on the library this was built
  against, three reporting 366 GB free and three reporting 61.1 TB.
- `PUT /api/v3/movie/{id}` with the body `GET` just returned, and `moveFiles`
  as a query parameter, answers 202 and changes nothing when it is false. The
  body is the whole resource, so it is round tripped rather than built.
- A movie carries `hasFile`, `sizeOnDisk`, `rootFolderPath` and `path`, and
  `status` is the release status (announced, inCinemas, released, deleted),
  which says nothing about the file. Checking that is not checking anything.

**The free space figure is Radarr's, and Radarr believes the share.** Those
61.1 TB are a 20 TB NAS over reporting, the same lie the `disk_sizes` setting
exists to correct on the Storage page. Radarr has no such correction, so the
number here is passed on as Radarr's own reading and labelled that way rather
than presented as the truth. Choosing a destination on it is still better than
choosing blind, and somebody who has told this app the real size can see both.

**Why a status check.** A move takes minutes and rewrites where every file of
a title lives. Three things make that unsafe and all of them are knowable:
somebody is watching it, the service is importing something for it, or this
app is partway through rewriting it. They are checked when the move is planned
and again immediately before it is asked for, because a plan somebody looked at
for two minutes is a plan about the past.
"""

from __future__ import annotations

import logging
import posixpath
from typing import Any

log = logging.getLogger(__name__)


def size_of(whole: dict[str, Any]) -> int:
    """How much the title takes up, whichever service holds it.

    A film carries `sizeOnDisk` at the top. A series keeps it under
    `statistics`, so reading only the top one measured every show as nought
    bytes and skipped the check that the destination has room for it.
    """
    top = whole.get("sizeOnDisk")
    if top:
        return int(top)
    return int((whole.get("statistics") or {}).get("sizeOnDisk") or 0)


def has_files(whole: dict[str, Any]) -> bool:
    """Whether there is anything to move.

    A film says `hasFile`. A series says how many episode files it has, and
    never says `hasFile` at all, so asking only for that made every show look
    like it had nothing to move.
    """
    if "hasFile" in whole:
        return bool(whole.get("hasFile"))
    stats = whole.get("statistics") or {}
    return bool(stats.get("episodeFileCount") or stats.get("sizeOnDisk"))


def is_a_show(whole: dict[str, Any]) -> bool:
    """Whether this is a series rather than a film.

    Worth saying out loud wherever it is shown, because the service keeps one
    path per series: moving an episode moves the whole show, and there is no
    such thing as moving one season somewhere else.
    """
    return "statistics" in whole and "movieFile" not in whole


async def destinations(service: Any) -> list[dict[str, Any]]:
    """Where this service could put a title, and what each one says it has.

    The space is the service's own reading. It is the figure that decides
    whether the move will actually fit, and it is also the figure that inherits
    whatever the share tells it, so it is named rather than presented as fact.
    """
    from app.integrations.base import get_json

    roots = await get_json(f"{service.base_url}/api/v3/rootfolder", headers=service.headers) or []
    return [
        {
            "id": root.get("id"),
            "path": (root.get("path") or "").rstrip("/") or root.get("path"),
            "free": root.get("freeSpace"),
            "accessible": bool(root.get("accessible")),
        }
        for root in roots
        if root.get("path")
    ]


async def _queue_for(service: Any, arr_id: int) -> list[dict[str, Any]]:
    """Whatever the service is downloading or importing for this title."""
    from app.integrations.base import get_json

    answer = await get_json(
        f"{service.base_url}/api/v3/queue", headers=service.headers, params={"pageSize": 200}
    )
    records = (answer or {}).get("records") or []
    key = "movieId" if service.path == "movie" else "seriesId"
    return [r for r in records if r.get(key) == arr_id]


# What the queue's own words mean, said as a person would. The interesting
# field is trackedDownloadState rather than status: a real queue read off a
# live server had two rows whose status was "completed" and whose state was
# "importBlocked", and "Radarr is completed a download" is not a sentence.
DOING = {
    "downloading": "is downloading something for it",
    "importing": "is importing something for it",
    "importpending": "has a download for it waiting to be imported",
    "importblocked": "has a download for it that it will not import by itself",
    "failedpending": "has a download for it that failed",
}


def _doing(item: dict[str, Any]) -> str:
    state = str(item.get("trackedDownloadState") or "").lower()
    if state in DOING:
        return DOING[state]
    if str(item.get("status") or "").lower() == "completed":
        return "has a finished download for it waiting"
    return "has a download for it in its queue"


def _busy_here(rating_key: int) -> list[str]:
    """What this app is doing to the file, which it would be doing to a file
    that is about to be somewhere else."""
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import MediaJob, Replacement
    from app.services.replacements import ACTIVE

    stopping = []
    with session_scope() as db:
        tidying = db.execute(
            select(MediaJob.id).where(MediaJob.rating_key == rating_key, MediaJob.status.in_(("queued", "running")))
        ).first()
        if tidying:
            stopping.append("this app is tidying it, which rewrites the file where it stands")
        replacing = db.execute(
            select(Replacement.id).where(Replacement.rating_key == rating_key, Replacement.status.in_(ACTIVE))
        ).first()
        if replacing:
            stopping.append("a replacement for it is still going")
    return stopping


async def _being_watched(rating_key: int) -> list[str]:
    """Whether somebody is watching it this second.

    Asked of the server rather than of the stream table, because the table is
    one poll old and the question is about the next few minutes.
    """
    from app.services.enforcer import live_context

    sessions, _context, error = await live_context()
    if error:
        # Not knowing is not the same as nobody watching, and a move is not
        # urgent. Said as a reason to stop rather than passed over.
        return [f"this app cannot see what is playing right now ({error})"]
    watching = [s for s in sessions if str(s.get("rating_key") or "") == str(rating_key)]
    if not watching:
        return []
    who = ", ".join(sorted({str(s.get("username") or "somebody") for s in watching}))
    return [f"it is being watched right now by {who}"]


async def blockers(service: Any, rating_key: int, movie: dict[str, Any]) -> list[str]:
    """Every reason this title must not be moved at this moment.

    All of them, not the first: somebody deciding whether to wait wants to know
    everything they are waiting for.
    """
    stopping: list[str] = []
    if not has_files(movie):
        stopping.append(f"{service.label} has no file for it, so there is nothing to move")
    queued = await _queue_for(service, movie.get("id"))
    if queued:
        stopping.append(f"{service.label} {_doing(queued[0])}")
    stopping += _busy_here(rating_key)
    stopping += await _being_watched(rating_key)
    return stopping


def _free_at(roots: list[dict[str, Any]], path: str) -> int | None:
    """What the service says is free where this title lives now."""
    for root in roots:
        if root["path"] == path:
            return root.get("free")
    return None


async def plan(service: Any, rating_key: int, movie: dict[str, Any], to_path: str) -> dict[str, Any]:
    """What moving this title would do, and whether it can be done now."""
    where_all = await destinations(service)
    where = [d for d in where_all if d["path"] == to_path.rstrip("/")]
    target = where[0] if where else None
    current = (movie.get("rootFolderPath") or "").rstrip("/")
    bytes_moved = size_of(movie)

    stopping = await blockers(service, rating_key, movie)
    worth_knowing: list[str] = []
    if target is None:
        stopping.append(f"{service.label} has no root folder at {to_path}")
    else:
        if not target["accessible"]:
            stopping.append(f"{service.label} cannot reach {to_path}")
        if target["path"] == current:
            stopping.append("it is already there")
        free = target.get("free")
        if free is not None and bytes_moved and free < bytes_moved:
            stopping.append(
                f"{service.label} says {to_path} has less room than the files need"
            )
        # Two roots on one disk report the same free space, and moving between
        # them frees nothing on the disk somebody is trying to empty. The
        # library this was built against has three roots on each of two disks,
        # so it is the obvious mistake rather than a far fetched one. A warning
        # and not a refusal: moving a title between libraries on one disk is a
        # reasonable thing to want, and identical figures are a strong hint
        # rather than proof that two paths share a device.
        if free is not None and free == _free_at(where_all, current) and current:
            worth_knowing.append(
                "that reports the same free space as where it is now, so the two are probably one disk "
                "and this would not free anything"
            )
    return {
        "rating_key": rating_key,
        "title": movie.get("title"),
        "service": service.label,
        "arr_id": movie.get("id"),
        "from": current or None,
        "to": target["path"] if target else to_path,
        "bytes": bytes_moved,
        # Said plainly wherever this is shown: the service keeps one path per
        # series, so an episode cannot be moved on its own and neither can a
        # season. Asking about either moves the show.
        "whole_show": is_a_show(movie),
        # Named rather than presented as the truth: it is the service's own
        # reading of the share, and a share that over reports fools it exactly
        # as it fools everything else.
        "free_at_destination": target.get("free") if target else None,
        "free_is_from": service.label,
        "blockers": stopping,
        # Things to think about rather than reasons to refuse.
        "warnings": worth_knowing,
        "can_move": not stopping,
    }


async def move(service: Any, rating_key: int, movie: dict[str, Any], to_path: str) -> dict[str, Any]:
    """Ask the service to move it.

    Only asks. Plex is told when the files have actually arrived, which is the
    job of whatever is watching: telling it here means a scan that runs before
    a single byte has moved, finds the file in neither place, and leaves both
    Plex and this app saying it is somewhere it is not.

    The checks run again here. A plan somebody read for two minutes is a plan
    about the past, and the things it checks are exactly the ones that start
    without warning.
    """
    import httpx

    checked = await plan(service, rating_key, movie, to_path)
    if not checked["can_move"]:
        raise ValueError("; ".join(checked["blockers"]))

    was = (movie.get("path") or "").rstrip("/")
    # Both, and `path` is the one that matters. The service decides whether
    # there is anything to move by comparing the path it is sent with the one
    # it holds, so sending a new rootFolderPath and leaving path alone is
    # asking it to move a title to where it already is. It answers 202, writes
    # nothing in its own history, and nothing moves: a real move asked for
    # that way looked like it worked and did not happen.
    folder = posixpath.basename(was) or posixpath.basename(
        (movie.get("folderName") or "").rstrip("/")
    )
    body = {**movie, "rootFolderPath": checked["to"]}
    if folder:
        body["path"] = posixpath.join(checked["to"], folder)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.put(
            f"{service.base_url}/api/v3/{service.path}/{movie['id']}",
            headers=service.headers, params={"moveFiles": "true"}, json=body,
        )
        response.raise_for_status()

    return {**checked, "asked": True, "was": was}


def settle(rating_key: int, old_folder: str | None) -> dict[str, Any]:
    """Tell Plex the file has arrived, then write down where it says it is.

    The row is read back rather than worked out. Plex and the service see the
    same disks through different mounts, so the path the service reports is
    not the one Plex uses and not one this container could open: copying it
    into the row would be writing a path nothing can find.

    Plex needs a moment to finish scanning, so it is asked more than once. If
    it never catches up the row is left alone and marked for re-reading, and
    the next library scan sorts it out: a stale path is better than a wrong
    one.
    """
    import time

    told = _tell_plex(rating_key, old_folder)
    for _ in range(TRIES_AFTER_LANDING):
        time.sleep(SETTLE_SECONDS)
        if _reread(rating_key, old_folder):
            return {**told, "row": True}
    # Plex could not answer for that item, which after a move it usually
    # cannot: it finds the file in its new folder, takes it in as a new thing
    # with a new number, and the old number stops existing. Measured on a real
    # move: the key answered 404 every time.
    #
    # So the old row is marked as one the library no longer has, which is what
    # every list here already filters on. The next library scan picks the file
    # up under its new number. Saying nothing instead would leave the card
    # naming the disk the file left, for as long as six hours, beside a panel
    # reading the new one.
    _no_longer_here(rating_key)
    return {**told, "row": False, "renumbered": True}


SETTLE_SECONDS = 5
"""How long to give Plex between asking it to scan and believing its answer."""

TRIES_AFTER_LANDING = 6
"""How many times to ask before leaving it to the next library scan. Thirty
seconds in all, against a scan of one folder that usually takes under one."""


def _reread(rating_key: int, old_folder: str | None) -> bool:
    """Write down where Plex now says the file is. True if it has moved on."""
    from app.db import session_scope
    from app.models import MediaItem
    from app.plex import library as plex_library

    try:
        found = plex_library.details([rating_key])
    except Exception as exc:  # noqa: BLE001 - the move itself worked
        log.debug("could not re-read %s after a move: %s", rating_key, exc)
        return False
    row = found[0] if found else None
    where = (row or {}).get("file_path")
    if not where:
        return False
    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is None:
            return False
        if item.file_path == where:
            # Plex is still answering with the old folder, so its scan has not
            # finished. Saying so is the difference between waiting and
            # writing down an answer that was never true.
            return False
        item.file_path = where
        if row.get("file_size"):
            item.file_size = row["file_size"]
        item.file_checked_at = None
    return True


def _no_longer_here(rating_key: int) -> None:
    """Mark the old row as one the library does not have any more.

    Not a new flag: every list here already hides what the last scan did not
    see, so saying the scan did not see it is how a thing stops being in the
    library. The file is not lost, it is under a new number, and the next scan
    finds it there.
    """
    from datetime import datetime

    from app.db import session_scope
    from app.models import MediaItem

    with session_scope() as db:
        item = db.get(MediaItem, rating_key)
        if item is not None:
            item.library_seen_at = datetime(1970, 1, 1)
            item.file_checked_at = None


def _tell_plex(rating_key: int, old_folder: str | None) -> dict[str, Any]:
    """Both folders, because one of them no longer holds the file.

    Only scanning the new one leaves Plex listing a file that is not there,
    which is the same hole tidying had before plex/maintenance.py existed, and
    the one anybody notices by pressing play.
    """
    from app.plex import maintenance

    done = {"old": False, "new": False}
    section = maintenance.section_of(rating_key)
    if section is None:
        return done
    for which, folder in (("old", old_folder), ("new", None)):
        if which == "old" and not folder:
            continue
        try:
            # The new one by rating key, since Plex is the one that has to find
            # where the service put it, and a partial scan of the old folder is
            # what loses the file that went.
            if which == "old":
                maintenance.rescan(section, folder)
            else:
                maintenance.rescan(section)
            done[which] = True
        except Exception as exc:  # noqa: BLE001 - the move itself worked
            log.warning("could not ask Plex to scan after a move (%s): %s", which, exc)
    return done


# ---- the queue ---------------------------------------------------------------
#
# One at a time, because a move is the disk reading and writing a whole file
# and two at once is each of them taking twice as long. The queue exists so
# somebody can pick fifty titles off a full array in one sitting and walk away,
# which is the only way this is any use at scale.

import asyncio  # noqa: E402

WATCH_EVERY = 15
"""Seconds between asking the service whether the move has landed. The move
takes minutes to hours, so this is cheap and still prompt."""

CEILING_HOURS = 8
"""How long one move may take before it is given up on. Generous, because a
large file across a network is slow and giving up early leaves the queue
stopped behind something that was going to work."""

RETRY_AFTER = 60
"""Seconds before going round again when every queued job is waiting on
something, such as somebody watching the title whose turn it is."""

FRUITLESS_ROUNDS = 5
"""Rounds where nothing could be started before the worker rests.

Without this it spins for ever on a job that cannot move, which is a task that
never ends and never says so. The five minute check starts it again, so a
queue waiting on somebody to stop watching still drains itself; it just does
so on that timer rather than on this loop."""

_running: Any = None


def queue(rating_key: int, service_name: str, arr_id: int | None, title: str | None,
          to_path: str, from_path: str | None, size: int | None, who: str | None) -> dict[str, Any]:
    """Put one title in the queue, or hand back the job already waiting for it."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    from app.db import session_scope
    from app.models import MoveJob

    with session_scope() as db:
        # Asking twice for the same title is somebody pressing twice, not a
        # second move: the first one is still going to happen.
        already = db.execute(
            select(MoveJob).where(MoveJob.rating_key == rating_key, MoveJob.status.in_(("queued", "moving")))
        ).scalars().first()
        if already is not None:
            return as_dict(already)
        job = MoveJob(
            rating_key=rating_key, title=title, service=service_name, arr_id=arr_id,
            to_path=to_path, from_path=from_path, bytes=size, status="queued",
            asked_by=who, created_at=datetime.now(UTC),
        )
        db.add(job)
        db.flush()
        return as_dict(job)


def as_dict(job: Any) -> dict[str, Any]:
    return {
        "id": job.id,
        "rating_key": job.rating_key,
        "title": job.title,
        "service": job.service,
        "arr_id": job.arr_id,
        "to": job.to_path,
        "from": job.from_path,
        "bytes": job.bytes,
        "status": job.status,
        "message": job.message,
        "asked_by": job.asked_by,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def listing(limit: int = 100) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import MoveJob

    with session_scope() as db:
        rows = db.execute(select(MoveJob).order_by(MoveJob.id.desc()).limit(limit)).scalars().all()
        return [as_dict(job) for job in rows]


def cancel(job_id: int) -> bool:
    """Take one out of the queue.

    A move already under way is left alone. The service is doing it, and
    stopping it halfway is how a file ends up in neither place.
    """
    from datetime import UTC, datetime

    from app.db import session_scope
    from app.models import MoveJob

    with session_scope() as db:
        job = db.get(MoveJob, job_id)
        if job is None or job.status != "queued":
            return False
        job.status = "cancelled"
        job.message = "Taken out of the queue"
        job.finished_at = datetime.now(UTC)
        return True


def _mark(job_id: int, **fields: Any) -> None:
    from app.db import session_scope
    from app.models import MoveJob

    with session_scope() as db:
        job = db.get(MoveJob, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)


def start_worker() -> None:
    """Make sure something is working through the queue."""
    global _running

    if _running is not None and not _running.done():
        return
    _running = asyncio.get_event_loop().create_task(_work())


def _waiting() -> list[int]:
    from sqlalchemy import select

    from app.db import session_scope
    from app.models import MoveJob

    with session_scope() as db:
        return list(db.execute(
            select(MoveJob.id).where(MoveJob.status == "queued").order_by(MoveJob.id)
        ).scalars())


async def _work() -> None:
    """Work through the queue, one title at a time.

    A job whose turn comes while something is happening to it is left queued
    with the reason written on it, and the next one is tried instead. Stopping
    the whole queue because the first title is being watched would mean a
    queue left overnight did nothing, and failing it would throw away a move
    somebody still wants.
    """
    fruitless = 0
    while True:
        ids = await asyncio.to_thread(_waiting)
        if not ids:
            return
        started_any = False
        for job_id in ids:
            if await _one(job_id):
                started_any = True
        if started_any:
            fruitless = 0
            continue
        fruitless += 1
        if fruitless >= FRUITLESS_ROUNDS:
            return
        await asyncio.sleep(RETRY_AFTER)


async def _one(job_id: int) -> bool:
    """Try one job. True if it was started, whatever became of it after."""
    from datetime import UTC, datetime

    from app.db import session_scope
    from app.integrations import arr
    from app.integrations.base import get_json
    from app.models import MoveJob

    def load():
        with session_scope() as db:
            job = db.get(MoveJob, job_id)
            return as_dict(job) if job is not None and job.status == "queued" else None

    job = await asyncio.to_thread(load)
    if job is None:
        return False
    service = arr.radarr if job["service"] == "radarr" else arr.sonarr
    if not service.configured():
        await asyncio.to_thread(_mark, job_id, message=f"{service.label} is not set up")
        return False

    try:
        whole = await get_json(
            f"{service.base_url}/api/v3/{service.path}/{job['arr_id']}", headers=service.headers
        )
    except Exception as exc:  # noqa: BLE001 - a blip is not a failed move
        await asyncio.to_thread(_mark, job_id, message=f"{service.label}: {exc}")
        return False
    if not whole:
        await asyncio.to_thread(
            _mark, job_id, status="failed", message=f"{service.label} no longer knows that title",
            finished_at=datetime.now(UTC),
        )
        return True

    checked = await plan(service, job["rating_key"], whole, job["to"])
    if not checked["can_move"]:
        # Still wanted, just not now. The reason is written down so the queue
        # says what it is waiting for rather than looking stuck.
        await asyncio.to_thread(_mark, job_id, message="; ".join(checked["blockers"]))
        return False

    await asyncio.to_thread(
        _mark, job_id, status="moving", message=None, started_at=datetime.now(UTC),
        from_path=checked["from"],
    )
    try:
        await move(service, job["rating_key"], whole, job["to"])
    except Exception as exc:  # noqa: BLE001 - one bad title must not stop the queue
        log.exception("move job %s could not be asked for", job_id)
        await asyncio.to_thread(
            _mark, job_id, status="failed", message=str(exc), finished_at=datetime.now(UTC)
        )
        return True

    await _watch(service, job_id, job["rating_key"], job["arr_id"], job["to"], checked["from"])
    return True


async def _watch(service: Any, job_id: int, rating_key: int, arr_id: int, to_path: str,
                 was: str | None = None) -> None:
    """Wait for the service to finish moving, so the next one starts after it.

    Asked of the title itself rather than of a named command, because the
    command's name is a thing to guess at across versions and where the file
    sits is the answer either way.
    """
    from datetime import UTC, datetime

    from app.integrations.base import get_json

    waited = 0
    while waited < CEILING_HOURS * 3600:
        await asyncio.sleep(WATCH_EVERY)
        waited += WATCH_EVERY
        try:
            whole = await get_json(
                f"{service.base_url}/api/v3/{service.path}/{arr_id}", headers=service.headers
            )
        except Exception as exc:  # noqa: BLE001 - a blip is not a failed move
            log.debug("could not check on move %s: %s", job_id, exc)
            continue
        if whole and has_landed(whole, to_path):
            # Now, not when it was asked for. Both folders, because one of
            # them no longer holds the file, and then the row is read back
            # from Plex so this app stops saying the old disk.
            await asyncio.to_thread(settle, rating_key, was)
            await asyncio.to_thread(
                _mark, job_id, status="done", message=None, finished_at=datetime.now(UTC)
            )
            return
    await asyncio.to_thread(
        _mark, job_id, status="failed", finished_at=datetime.now(UTC),
        message=f"It had not landed after {CEILING_HOURS} hours, so the queue moved on. Check {service.label}.",
    )


def has_landed(whole: dict[str, Any], to_path: str) -> bool:
    """Whether the title is now where it was asked to go.

    Both the folder the service records and where the file actually sits. The
    record changes first, so taking that alone as done starts the next move
    while the disk is still copying this one, which is the whole thing a queue
    of one at a time exists to avoid.
    """
    where = (whole.get("rootFolderPath") or "").rstrip("/")
    if where != to_path.rstrip("/"):
        return False
    file_at = (whole.get("movieFile") or {}).get("path") or whole.get("path") or ""
    return has_files(whole) and str(file_at).startswith(to_path.rstrip("/"))


async def resume() -> str:
    """Pick the queue back up, including a move that was in flight.

    A move takes minutes to hours and the app can be restarted in the middle
    of one. The job is then left saying "moving" with nothing watching it, so
    the queue would stop there for ever with no sign of why.

    A move already asked for is not asked for again. The service was told and
    is either still doing it or has finished, and re-issuing it would either
    do nothing or start a second copy of the same work. So it is looked at:
    landed means done, and anything else means watch it again from here.
    """
    from sqlalchemy import func, select

    from app.db import session_scope
    from app.integrations import arr
    from app.integrations.base import get_json
    from app.models import MoveJob

    def in_flight():
        with session_scope() as db:
            return [
                as_dict(job)
                for job in db.execute(select(MoveJob).where(MoveJob.status == "moving")).scalars()
            ]

    def still_queued():
        with session_scope() as db:
            return db.execute(
                select(func.count()).select_from(MoveJob).where(MoveJob.status == "queued")
            ).scalar() or 0

    picked_up = 0
    for job in await asyncio.to_thread(in_flight):
        service = arr.radarr if job["service"] == "radarr" else arr.sonarr
        if not service.configured():
            continue
        try:
            whole = await get_json(
                f"{service.base_url}/api/v3/{service.path}/{job['arr_id']}", headers=service.headers
            )
        except Exception as exc:  # noqa: BLE001 - try again on the next round
            log.debug("could not look at move %s: %s", job["id"], exc)
            continue
        if whole and has_landed(whole, job["to"]):
            from datetime import UTC, datetime

            await asyncio.to_thread(
                _mark, job["id"], status="done", message=None, finished_at=datetime.now(UTC)
            )
            continue
        # Still going, and nothing is watching it any more.
        asyncio.get_event_loop().create_task(
            _watch(service, job["id"], job["rating_key"], job["arr_id"], job["to"], job["from"])
        )
        picked_up += 1

    waiting = await asyncio.to_thread(still_queued)
    if waiting:
        start_worker()
    if not waiting and not picked_up:
        return ""
    return f"{waiting} waiting, {picked_up} picked back up"
