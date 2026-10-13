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
from typing import Any

log = logging.getLogger(__name__)


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
    if not movie.get("hasFile"):
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
    bytes_moved = int(movie.get("sizeOnDisk") or 0)

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
    """Ask the service to move it, then tell Plex about both folders.

    The checks run again here. A plan somebody read for two minutes is a plan
    about the past, and the things it checks are exactly the ones that start
    without warning.
    """
    import httpx

    checked = await plan(service, rating_key, movie, to_path)
    if not checked["can_move"]:
        raise ValueError("; ".join(checked["blockers"]))

    was = (movie.get("path") or "").rstrip("/")
    body = {**movie, "rootFolderPath": checked["to"]}
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.put(
            f"{service.base_url}/api/v3/{service.path}/{movie['id']}",
            headers=service.headers, params={"moveFiles": "true"}, json=body,
        )
        response.raise_for_status()

    told = _tell_plex(rating_key, was)
    return {**checked, "asked": True, "was": was, "plex": told}


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
