"""Version, changelog and update checks. GitHub is faked; nothing leaves."""

import asyncio
import pathlib
import re

import httpx

from tests.test_auth import claim

REAL_CLIENT = httpx.AsyncClient
ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_version_matches_pyproject_package_and_changelog():
    from app.version import VERSION, changelog

    pyproject = (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1) == VERSION
    package = (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    assert f'"version": "{VERSION}"' in package
    entries = changelog()
    assert entries and entries[0]["version"] == VERSION and entries[0]["date"]
    assert all(e["sections"] and all(s["items"] for s in e["sections"]) for e in entries)


def test_parse_changelog():
    from app.version import parse_changelog

    text = "# Changelog\n\nIntro - ignored\n\n## 1.2.0 - 2026-01-02\n\n### Added\n- One\n  continued\n- Two\n\n## v1.1.9\n- Loose\n"
    assert parse_changelog(text) == [
        {"version": "1.2.0", "date": "2026-01-02", "sections": [{"title": "Added", "items": ["One continued", "Two"]}]},
        {"version": "1.1.9", "date": None, "sections": [{"title": "Changes", "items": ["Loose"]}]},
    ]


def _fake_github(monkeypatch, behind=2, changelog="## 9.0.0 - 2030-01-01\n### Added\n- Future\n", repo_status=200):
    from app.version import VERSION

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if path == "/repos/o/r":
            return httpx.Response(repo_status, json={"default_branch": "main", "html_url": "https://github.com/o/r"})
        if path == "/repos/o/r/commits/main":
            return httpx.Response(200, json={"sha": "f" * 40, "commit": {"committer": {"date": "2030-01-01T00:00:00Z"}}})
        if path == "/repos/o/r/contents/CHANGELOG.md":
            return httpx.Response(200, text=changelog + f"## {VERSION} - 2026-01-01\n- Now\n")
        if path.startswith("/repos/o/r/compare/"):
            commits = [{"sha": f"{i:040x}", "html_url": "u", "commit": {"message": f"Change {i}\n\nbody", "committer": {"date": None}}}
                       for i in range(behind)]
            return httpx.Response(200, json={"ahead_by": behind, "commits": commits})
        return httpx.Response(404)

    def client(*args, **kwargs):
        return REAL_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return seen


def test_update_available_by_commit_and_flagged(client, monkeypatch):
    from app import version

    claim(client)
    monkeypatch.setenv("GIT_COMMIT", "a" * 40)
    version.commit.cache_clear()
    client.put("/api/settings", json={"update_repository": "o/r", "update_github_token": "ghp_secretvalue"})
    seen = _fake_github(monkeypatch)

    result = client.post("/api/about/check").json()
    assert result["status"] == "update_available" and result["commits_behind"] == 2
    assert [c["message"] for c in result["commits"]] == ["Change 1", "Change 0"]
    assert [v["version"] for v in result["newer"]] == ["9.0.0"]
    # The registry is asked first now, so pick GitHub's own requests out.
    to_github = [r for r in seen if r.url.host == "api.github.com"]
    assert to_github and to_github[0].headers["authorization"] == "Bearer ghp_secretvalue"
    assert client.get("/api/about/status").json()["status"] == "update_available"
    about = client.get("/api/about").json()
    assert about["commit"] == "a" * 40 and about["update"]["latest_version"] == "9.0.0"
    assert "ghp_secretvalue" not in str(about)
    version.commit.cache_clear()


def test_up_to_date_and_errors_keep_the_last_answer(client, monkeypatch):
    from app import version

    claim(client)
    monkeypatch.setenv("GIT_COMMIT", "b" * 40)
    version.commit.cache_clear()
    client.put("/api/settings", json={"update_repository": "o/r"})
    _fake_github(monkeypatch, behind=0, changelog="")
    assert client.post("/api/about/check").json()["status"] == "up_to_date"

    _fake_github(monkeypatch, repo_status=404)
    failed = client.post("/api/about/check").json()
    assert failed["status"] == "error" and "private" in failed["message"]
    assert failed["latest_commit"] == "f" * 40  # still shown from the last good check
    version.commit.cache_clear()


def test_without_a_commit_versions_compare(client, monkeypatch):
    from app import version
    from app.services import updates

    monkeypatch.setenv("GIT_COMMIT", "")
    monkeypatch.setattr(version, "_from_checkout", lambda: None)
    version.commit.cache_clear()
    _fake_github(monkeypatch)
    result = asyncio.run(updates.fetch("o/r", "", version.commit()))
    assert result["compared_by"] == "version" and result["status"] == "update_available"

    _fake_github(monkeypatch, changelog="")
    assert asyncio.run(updates.fetch("o/r", "", None))["status"] == "up_to_date"
    version.commit.cache_clear()


def test_a_bad_repository_name_is_refused_without_asking(monkeypatch):
    from app.services import updates

    seen = _fake_github(monkeypatch)
    for bad in ("", "o", "o/r/../x", "https://github.com/o/r"):
        try:
            asyncio.run(updates.fetch(bad))
        except updates.CheckFailed:
            pass
        else:
            raise AssertionError(bad)
    assert not seen


def test_viewers_cannot_check(client):
    from tests.test_privacy import as_viewer

    as_viewer(client, "all")
    assert client.get("/api/about").status_code == 403
    assert client.post("/api/about/check").status_code == 403


def test_commits_that_are_not_a_release_are_not_an_update(client, monkeypatch):
    """The About page said "Update available, 1 commit behind" pointing at a
    commit that only changed the README. The image is built per release and
    documentation does not rebuild it at all, so the Docker tab had nothing to
    pull and Apply did nothing. A release is the thing anyone can install."""
    from app import version

    claim(client)
    monkeypatch.setenv("GIT_COMMIT", "c" * 40)
    version.commit.cache_clear()
    client.put("/api/settings", json={"update_repository": "o/r"})
    # Two commits ahead, and the newest release on GitHub is the one installed.
    _fake_github(monkeypatch, behind=2, changelog="")

    result = client.post("/api/about/check").json()
    assert result["status"] == "up_to_date"
    assert result["commits_behind"] == 2, "what has happened since is still worth showing"
    assert result["compared_by"] == "version"
    version.commit.cache_clear()


def test_without_a_changelog_commits_still_decide(client, monkeypatch):
    """A fork with no CHANGELOG.md has nothing but commits to go on, and
    being told nothing at all is worse than being told it is behind."""
    from app import version

    claim(client)
    monkeypatch.setenv("GIT_COMMIT", "d" * 40)
    version.commit.cache_clear()
    client.put("/api/settings", json={"update_repository": "o/r"})

    seen = _fake_github(monkeypatch, behind=3)
    monkeypatch.setattr("app.services.updates.parse_changelog", lambda text: [])

    result = client.post("/api/about/check").json()
    assert result["status"] == "update_available"
    assert result["compared_by"] == "commit" and result["commits_behind"] == 3
    assert seen, "GitHub was asked"
    version.commit.cache_clear()


def _fake_registry(monkeypatch, tags=("0.1.0", "9.9.9", "latest", "sha-abc"), challenge=True, status=200):
    """A registry that makes anyone asking about a public image do the token
    dance first, the way GHCR and Docker Hub both do."""
    handed = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/token":
            handed.append(dict(request.url.params))
            return httpx.Response(200, json={"token": "anonymous-pull"})
        if path.endswith("/tags/list"):
            if challenge and request.headers.get("authorization") != "Bearer anonymous-pull":
                return httpx.Response(
                    401, headers={"www-authenticate": 'Bearer realm="https://ghcr.io/token",service="ghcr.io"'}
                )
            return httpx.Response(status, json={"tags": list(tags)})
        return httpx.Response(404)

    def client(*args, **kwargs):
        return REAL_CLIENT(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return handed


def test_the_registry_decides_even_when_the_repository_cannot_be_read(client, monkeypatch):
    """Somebody given the image has no access to a private repository. Before
    this they got "GitHub can't find Shuamann/Cartographarr" on their settings
    page for ever and were never told an update existed."""
    from app import version

    claim(client)
    monkeypatch.setenv("GIT_COMMIT", "e" * 40)
    version.commit.cache_clear()
    # The GitHub half of the fake answers 404 for everything.
    handed = _fake_registry(monkeypatch)

    result = client.post("/api/about/check").json()
    assert result["status"] == "update_available"
    assert result["latest_version"] == "9.9.9", "the newest version tag, not the newest tag"
    assert result["compared_by"] == "image"
    assert result["notes_error"], "the repository failure is kept, quietly"
    assert handed and "repository" in handed[0]["scope"], "asked for an anonymous pull token"
    assert client.get("/api/about/status").json()["status"] == "update_available"
    version.commit.cache_clear()


def test_the_published_image_outranks_a_release_note(client, monkeypatch):
    """A changelog entry is written before the image that carries it is built.
    Saying an update is ready while the Docker tab has nothing to pull is the
    exact thing this check was changed to stop doing."""
    from app import version
    from app.services import updates

    claim(client)
    monkeypatch.setenv("GIT_COMMIT", "f" * 40)
    version.commit.cache_clear()
    client.put("/api/settings", json={"update_repository": "o/r"})
    _fake_github(monkeypatch)  # a 9.0.0 entry in the changelog on GitHub
    monkeypatch.setattr(updates, "published", _answers([version.VERSION]))

    result = client.post("/api/about/check").json()
    assert result["status"] == "up_to_date", "nothing is published past what is installed"
    assert [v["version"] for v in result["newer"]] == ["9.0.0"], "the note is still read and kept"
    version.commit.cache_clear()


def test_a_registry_that_will_not_answer_falls_back_to_the_notes(client, monkeypatch):
    from app import version
    from app.services import updates

    claim(client)
    monkeypatch.setenv("GIT_COMMIT", "a" * 40)
    version.commit.cache_clear()
    client.put("/api/settings", json={"update_repository": "o/r"})
    _fake_github(monkeypatch)
    monkeypatch.setattr(updates, "published", _raises("The registry has no image called x/y."))

    result = client.post("/api/about/check").json()
    assert result["status"] == "update_available" and result["compared_by"] == "version"
    version.commit.cache_clear()


def test_tags_that_are_not_versions_are_ignored(client, monkeypatch):
    """`latest` moves, and a sha tag is not a version. Sorting tags as text
    would also make 0.9.0 newer than 0.10.0."""
    import asyncio

    from app.services import updates

    _fake_registry(monkeypatch, tags=("latest", "0.9.0", "0.10.0", "sha-deadbee", "v0.2.0"))
    assert asyncio.run(updates.published("ghcr.io/o/r")) == ["0.10.0", "0.9.0", "0.2.0"]


def test_an_image_that_is_not_an_image_is_refused_without_asking(monkeypatch):
    import asyncio

    import pytest

    from app.services import updates

    asked = _fake_registry(monkeypatch)
    with pytest.raises(updates.CheckFailed):
        asyncio.run(updates.published("cartographarr"))
    assert asked == [], "nothing was asked of anybody"


def _answers(tags):
    """A registry stub for tests about what is done with the answer."""

    async def published(image):
        return list(tags)

    return published


def _raises(message):
    async def published(image):
        from app.services.updates import CheckFailed

        raise CheckFailed(message)

    return published
