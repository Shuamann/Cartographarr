"""Finding a library under a mounted root, rather than being told where it is.

Plex reports a path from the server's point of view, `/movies/A Film/a.mkv`,
and the container sees whatever was mounted into it. Rather than one mount per
library and a pair typed in for each, the app is given the directory they all
sit in and works the rest out by looking. These are the shapes that looking has
to cope with: the library under the root, the root that is itself the library,
two roots, and a path that is nowhere at all.
"""

from app.services import mediafix
from app.settings_store import trial
from tests.test_auth import claim


def make(tmp_path, *relative):
    """Lay down real files, because the whole point is that it stats them."""
    for part in relative:
        target = tmp_path / part
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"")
    return str(tmp_path).replace("\\", "/")


def test_a_library_is_found_under_the_root(tmp_path):
    root = make(tmp_path, "movies/A Film/a.mkv")
    with trial({"media_roots": root}):
        assert mediafix.local_path("/movies/A Film/a.mkv") == f"{root}/movies/A Film/a.mkv"


def test_the_root_can_be_the_library_itself(tmp_path):
    """Mounting one share straight in still has to work, name dropped."""
    root = make(tmp_path, "A Film/a.mkv")
    with trial({"media_roots": root}):
        assert mediafix.local_path("/movies/A Film/a.mkv") == f"{root}/A Film/a.mkv"


def test_the_second_root_is_tried_when_the_first_has_nothing(tmp_path):
    first = tmp_path / "pool1"
    second = tmp_path / "pool2"
    first.mkdir()
    make(second, "tv/A Show/s01e01.mkv")
    roots = f"{str(first).replace(chr(92), '/')}, {str(second).replace(chr(92), '/')}"
    with trial({"media_roots": roots}):
        here = mediafix.local_path("/tv/A Show/s01e01.mkv")
    assert here == f"{str(second).replace(chr(92), '/')}/tv/A Show/s01e01.mkv"


def test_a_file_nowhere_under_the_roots_is_not_claimed(tmp_path):
    root = make(tmp_path, "movies/A Film/a.mkv")
    with trial({"media_roots": root}):
        assert mediafix.local_path("/tv/A Show/s01e01.mkv") is None


def test_no_roots_set_leaves_the_old_behaviour_alone(tmp_path):
    """A share mounted at the path Plex reports needs no settings at all."""
    make(tmp_path, "a.mkv")
    with trial({"media_roots": "", "media_path_map": ""}):
        assert mediafix.local_path(str(tmp_path / "a.mkv").replace("\\", "/"))
        assert mediafix.local_path("/movies/A Film/a.mkv") is None


def test_a_typed_mapping_still_wins(tmp_path):
    """The escape hatch, for a name that cannot be guessed from the path."""
    root = make(tmp_path, "oddly named/A Film/a.mkv")
    with trial({"media_roots": root, "media_path_map": f"/movies={root}/oddly named"}):
        assert mediafix.local_path("/movies/A Film/a.mkv") == f"{root}/oddly named/A Film/a.mkv"


def test_the_second_file_in_a_library_costs_one_look(tmp_path, monkeypatch):
    """Where a library lives is worked out once, not once per file."""
    root = make(tmp_path, "movies/A Film/a.mkv", "movies/B Film/b.mkv")
    import os

    with trial({"media_roots": root}):
        assert mediafix.local_path("/movies/A Film/a.mkv")

        looks = []
        real = os.path.exists
        monkeypatch.setattr(os.path, "exists", lambda p: looks.append(p) or real(p))
        assert mediafix.local_path("/movies/B Film/b.mkv") == f"{root}/movies/B Film/b.mkv"

    assert looks == [f"{root}/movies/B Film/b.mkv"]


def test_a_changed_setting_throws_the_memory_away(tmp_path):
    """Otherwise a root removed in Settings would keep answering."""
    root = make(tmp_path, "movies/A Film/a.mkv")
    with trial({"media_roots": root}):
        assert mediafix.local_path("/movies/A Film/a.mkv")
    with trial({"media_roots": "/nowhere"}):
        assert mediafix.local_path("/movies/A Film/a.mkv") is None


# ---- what Settings shows ----------------------------------------------------

def test_each_library_is_reported_once_with_where_it_landed(tmp_path):
    root = make(tmp_path, "movies/A Film/a.mkv", "movies/B Film/b.mkv")
    paths = ["/movies/A Film/a.mkv", "/movies/B Film/b.mkv", "/tv/A Show/s01e01.mkv"]
    with trial({"media_roots": root}):
        rows = mediafix.where_libraries(paths)

    assert [row["library"] for row in rows] == ["/movies", "/tv"]
    films, shows = rows
    assert films["found"] and films["here"] == f"{root}/movies"
    assert films["files"] == 2
    assert not shows["found"] and shows["here"] is None
    assert shows["example"] == "/tv/A Show/s01e01.mkv"


def test_nothing_known_reports_nothing(tmp_path):
    with trial({"media_roots": str(tmp_path).replace("\\", "/")}):
        assert mediafix.where_libraries([]) == []


# ---- picking a path rather than typing one ----------------------------------

def test_the_container_lists_what_it_can_see(client, tmp_path):
    """Which directories exist in a container is a question only it can answer."""
    share = tmp_path / "share"
    (share / "movies").mkdir(parents=True)
    (share / "tv").mkdir()
    (share / ".hidden").mkdir()
    (share / "a.mkv").write_bytes(b"")

    claim(client)
    here = str(share).replace("\\", "/")
    answer = client.get("/api/library/tidy/directories", params={"path": here}).json()

    assert answer["path"] == here
    assert [row["name"] for row in answer["directories"]] == ["movies", "tv"]
    assert answer["directories"][0]["path"] == f"{here}/movies"
    assert answer["parent"]


def test_a_half_typed_path_lists_the_directory_it_is_inside(client, tmp_path):
    """So the list is there to complete from while somebody is still typing."""
    share = tmp_path / "share"
    (share / "movies").mkdir(parents=True)

    claim(client)
    here = str(share).replace("\\", "/")
    answer = client.get("/api/library/tidy/directories", params={"path": f"{here}/mov"}).json()

    assert answer["path"] == here
    assert [row["name"] for row in answer["directories"]] == ["movies"]


def test_listing_is_admin_only(client):
    assert client.get("/api/library/tidy/directories").status_code in (401, 403)


# ---- when the names do not line up ------------------------------------------

def test_a_library_is_found_by_its_files_when_the_name_does_not_match(tmp_path):
    """Plex maps its own container paths, so /movies here can be Films there."""
    root = make(tmp_path, "Films/A Film/a.mkv")
    with trial({"media_roots": root}):
        assert mediafix.local_path("/movies/A Film/a.mkv") == f"{root}/Films/A Film/a.mkv"


def test_the_search_reaches_a_library_one_level_further_down(tmp_path):
    root = make(tmp_path, "Archive/Films/A Film/a.mkv")
    with trial({"media_roots": root}):
        assert mediafix.local_path("/movies/A Film/a.mkv") == f"{root}/Archive/Films/A Film/a.mkv"


def test_a_library_really_absent_is_searched_for_once(tmp_path, monkeypatch):
    """A walk per file would be a walk per row on a page listing two hundred."""
    root = make(tmp_path, "Films/A Film/a.mkv")
    import os

    with trial({"media_roots": root}):
        assert mediafix.local_path("/tv/A Show/s01e01.mkv") is None

        walks = []
        real = os.scandir
        monkeypatch.setattr(os, "scandir", lambda p: walks.append(p) or real(p))
        assert mediafix.local_path("/tv/A Show/s01e02.mkv") is None

    assert walks == []


def test_a_root_says_what_is_inside_it(tmp_path):
    """The one thing nobody can see from outside the container."""
    share = tmp_path / "share"
    (share / "Films").mkdir(parents=True)
    (share / "Shows").mkdir()
    root = str(share).replace("\\", "/")

    with trial({"media_roots": f"{root}, /nowhere-at-all"}):
        here, missing = mediafix.root_status()

    assert here["path"] == root and here["exists"]
    assert here["contains"] == ["Films", "Shows"]
    assert not missing["exists"] and missing["contains"] == []
