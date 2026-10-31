"""Is a newer Cartographarr out?

Two questions, to two places. The registry is asked which versions are
published, and that decides the answer, because a tag is an image somebody can
pull where a release note is only a promise. GitHub is asked for the
CHANGELOG.md and the commits since this build, which is the detail: what the
update brings. A registry answers anybody about a public image, so an install
that cannot read the repository, a fork or a copy given to a friend, still
learns that an update is waiting instead of showing an error it cannot fix.

The answer is kept, so the About page and the flag on Settings do not ask on
every page load.

Nothing about this install is sent to either: no settings, no counts, no
identifiers. They see an address asking about a public thing, the same as a
browser would. While the repository is private, the notes need a token with
read access; the verdict does not.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from app.redact import redact
from app.version import VERSION, commit, parse_changelog, parse_version

log = logging.getLogger(__name__)

API = "https://api.github.com"
STATE_KEY = "update_check"
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MAX_COMMITS = 30
VERSION_TAG = re.compile(r"^v?(\d+\.\d+\.\d+)$")


class CheckFailed(Exception):
    """A reason worth showing as it is."""


def _explain(response: httpx.Response, repo: str, has_token: bool) -> str:
    if response.status_code == 401:
        return "GitHub refused the token. Check it has not expired."
    if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
        return "GitHub's hourly limit for checks was reached. It will try again later, or add a token."
    if response.status_code in (403, 404):
        if has_token:
            return f"GitHub can't find {repo}, or the token can't read it."
        return f"GitHub can't find {repo}. If the repository is private, add a token with read access."
    return f"GitHub answered {response.status_code}."


async def _get(gh: httpx.AsyncClient, path: str, repo: str, has_token: bool, **kwargs) -> httpx.Response:
    try:
        response = await gh.get(path, **kwargs)
    except httpx.HTTPError as exc:
        raise CheckFailed(f"Could not reach GitHub: {redact(exc) or type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise CheckFailed(_explain(response, repo, has_token))
    return response


async def _registry_token(rg: httpx.AsyncClient, refused: httpx.Response, host: str, path: str) -> str:
    """The anonymous pull token a registry hands anybody for a public image.

    Registries answer an unauthenticated read with a 401 that says where to go
    and what to ask for, so the challenge is read rather than guessed and this
    works on GHCR and on Docker Hub without knowing anything about either.
    """
    told = dict(re.findall(r'(\w+)="([^"]*)"', refused.headers.get("www-authenticate", "")))
    params = {"scope": told.get("scope") or f"repository:{path}:pull"}
    if told.get("service"):
        params["service"] = told["service"]
    try:
        answer = await rg.get(told.get("realm") or f"https://{host}/token", params=params)
    except httpx.HTTPError as exc:
        raise CheckFailed(f"Could not reach the registry: {redact(exc) or type(exc).__name__}") from exc
    if answer.status_code >= 400:
        raise CheckFailed("The registry would not hand out a token to read that image.")
    body = answer.json()
    return body.get("token") or body.get("access_token") or ""


async def published(image: str) -> list[str]:
    """Which versions exist as tags on the image, newest first."""
    name = image.strip()
    host, _, path = name.partition("/")
    path = path.split(":")[0]
    if not path or "." not in host:
        raise CheckFailed("The image should look like ghcr.io/owner/name.")

    url = f"https://{host}/v2/{path}/tags/list"
    headers = {"User-Agent": f"Cartographarr/{VERSION}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=headers) as rg:
        try:
            response = await rg.get(url)
            if response.status_code == 401:
                token = await _registry_token(rg, response, host, path)
                response = await rg.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise CheckFailed(f"Could not reach the registry: {redact(exc) or type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise CheckFailed(f"The registry will not show the tags of {name}. Is the image public?")
        if response.status_code == 404:
            raise CheckFailed(f"The registry has no image called {name}.")
        if response.status_code >= 400:
            raise CheckFailed(f"The registry answered {response.status_code}.")
        tags = (response.json() or {}).get("tags") or []

    found = {m.group(1) for tag in tags if (m := VERSION_TAG.match(str(tag)))}
    return sorted(found, key=lambda v: parse_version(v) or (), reverse=True)


async def fetch(repo: str, token: str = "", installed_commit: str | None = None) -> dict[str, Any]:
    if not REPOSITORY.match(repo):
        raise CheckFailed("The repository should look like owner/name.")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Cartographarr/{VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    has_token = bool(token)

    async with httpx.AsyncClient(base_url=API, headers=headers, timeout=15, follow_redirects=True) as gh:
        info = (await _get(gh, f"/repos/{repo}", repo, has_token)).json()
        branch = info.get("default_branch") or "main"
        head = (await _get(gh, f"/repos/{repo}/commits/{branch}", repo, has_token)).json()
        latest_sha = head.get("sha")

        remote_log: list[dict[str, Any]] = []
        try:
            raw = await gh.get(f"/repos/{repo}/contents/CHANGELOG.md", params={"ref": branch},
                               headers={"Accept": "application/vnd.github.raw+json"})
            if raw.status_code == 200:
                remote_log = parse_changelog(raw.text)
        except httpx.HTTPError as exc:
            log.debug("changelog unavailable: %s", redact(exc))

        behind: int | None = None
        commits: list[dict[str, Any]] = []
        compared = False
        if installed_commit and latest_sha:
            if latest_sha.startswith(installed_commit):
                behind, compared = 0, True
            else:
                response = await gh.get(f"/repos/{repo}/compare/{installed_commit}...{latest_sha}")
                if response.status_code == 200:
                    data = response.json()
                    compared = True
                    behind = int(data.get("ahead_by") or 0)
                    for c in reversed((data.get("commits") or [])[-MAX_COMMITS:]):
                        commits.append({
                            "sha": c.get("sha"),
                            "message": ((c.get("commit") or {}).get("message") or "").splitlines()[0][:200],
                            "date": ((c.get("commit") or {}).get("committer") or {}).get("date"),
                            "url": c.get("html_url"),
                        })
                elif response.status_code != 404:
                    # 404 is a commit GitHub has never seen: a local build. Versions still compare.
                    raise CheckFailed(_explain(response, repo, has_token))

    latest_version = remote_log[0]["version"] if remote_log else None
    mine = parse_version(VERSION)
    newer = [v for v in remote_log if (parse_version(v["version"]) or ()) > (mine or ())]
    # A release is what there is to install. The image is built per release and
    # a documentation commit does not rebuild it at all, so counting commits
    # flagged an update that nothing could pull: the Docker tab had nothing new
    # and Apply did nothing. Commits are still read and shown, as what has
    # happened since, but they no longer decide the answer. Without a changelog
    # to read there is nothing but commits to go on, and behind is better than
    # silence.
    if latest_version:
        available = bool(newer)
    elif compared:
        available = bool(behind)
    else:
        raise CheckFailed("GitHub has no CHANGELOG.md to compare with, and this build does not know its commit.")

    return {
        "status": "update_available" if available else "up_to_date",
        "message": None,
        "compared_by": "version" if latest_version else "commit",
        "latest_version": latest_version,
        "latest_commit": latest_sha,
        "latest_date": ((head.get("commit") or {}).get("committer") or {}).get("date"),
        "commits_behind": behind,
        "commits": commits,
        "newer": newer,
        "repository_url": info.get("html_url") or f"https://github.com/{repo}",
        "branch": branch,
    }


def stored() -> dict[str, Any] | None:
    from app.db import session_scope
    from app.models import SyncState

    with session_scope() as db:
        row = db.get(SyncState, STATE_KEY)
        if row is None:
            return None
        try:
            data = json.loads(row.value)
        except ValueError:
            return None
    # A check made before this install was updated says nothing about it now.
    if data.get("installed_version") != VERSION or data.get("installed_commit") != commit():
        return None
    return data


def _store(data: dict[str, Any]) -> None:
    from app.db import session_scope
    from app.models import SyncState

    with session_scope() as db:
        db.merge(SyncState(key=STATE_KEY, value=json.dumps(data)))


async def check() -> dict[str, Any]:
    """Check now and keep the answer. A failure keeps what was last known."""
    import asyncio

    from app.settings_store import current

    settings = current()
    installed = commit()
    base = {"checked_at": datetime.now(UTC).isoformat(), "installed_version": VERSION, "installed_commit": installed}

    # The registry decides, the repository explains. Anybody can read the tags
    # of a public image, so an install that cannot see the repository still
    # learns that an update exists, which is the difference between a copy of
    # this that tells its owner nothing and one that tells them to press Apply.
    newest: str | None = None
    registry_failed: str | None = None
    if settings.update_image.strip():
        try:
            tags = await published(settings.update_image.strip())
            newest = tags[0] if tags else None
        except CheckFailed as exc:
            registry_failed = str(exc)

    notes: dict[str, Any] = {}
    notes_failed: str | None = None
    if settings.update_repository.strip():
        try:
            notes = await fetch(settings.update_repository.strip(), settings.update_github_token.strip(), installed)
        except CheckFailed as exc:
            # Not an error anybody needs to see while the registry answers:
            # the release notes are the detail, not the verdict.
            notes_failed = str(exc)
            log.info("release notes unavailable: %s", exc)

    if newest is None and not notes:
        previous = await asyncio.to_thread(stored) or {}
        # Both were asked and neither answered, so say both reasons: one of
        # them is usually a setting with a typo in it.
        why = "; ".join(filter(None, (registry_failed, notes_failed)))
        result = {**previous, **base, "status": "error", "message": why or "Nothing to check against."}
    else:
        result = {**base, **notes, "message": None, "notes_error": notes_failed}
        if newest is not None:
            result["status"] = (
                "update_available" if (parse_version(newest) or ()) > (parse_version(VERSION) or ()) else "up_to_date"
            )
            result["compared_by"] = "image"
            result["latest_version"] = newest
    await asyncio.to_thread(_store, result)
    return result


def summary(result: dict[str, Any]) -> str:
    if result["status"] == "error":
        raise RuntimeError(result["message"])
    if result["status"] == "up_to_date":
        return f"up to date ({VERSION})"
    parts = []
    if result.get("latest_version") and result["latest_version"] != VERSION:
        parts.append(f"{result['latest_version']} available")
    if result.get("commits_behind"):
        parts.append(f"{result['commits_behind']} commits behind")
    return ", ".join(parts) or "update available"
