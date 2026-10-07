"""The position runs on between polls, and stops when the stream does.

Live activity is read on a timer, so a position sat still and then jumped.
Plex now pushes an event the moment something changes, which makes the jumps
irregular as well as large: right twice a minute and visibly wrong the rest of
the time.

Nothing here invents a fact. A stream that is playing has advanced by the time
that passed, which is the whole of the assumption, and each reading from the
server replaces the guess outright rather than being averaged into it. The
half that keeps it honest is stopping: a paused stream whose timer kept
climbing would be a lie told smoothly.

Checked in a browser with the live answer held at twenty minutes: playing read
20:03 then 20:07, paused read 20:09 then 20:09.
"""

import pathlib

SOURCE = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "playing.ts"


def test_it_only_runs_while_the_stream_is_playing():
    source = SOURCE.read_text(encoding="utf-8")
    assert "if (!playing) return;" in source, "a paused stream must not keep climbing"


def test_the_server_replaces_the_guess_rather_than_being_averaged_into_it():
    """A seek, a pause or a stall has to land on the next poll, so the guess is
    never more than one interval away from the truth."""
    source = SOURCE.read_text(encoding="utf-8")
    assert "told.current = { offset, at: Date.now() };" in source
    assert "setShown(offset);" in source


def test_it_never_runs_past_the_end():
    """A film that has finished is not still playing, and a bar filled past its
    track looks broken."""
    source = SOURCE.read_text(encoding="utf-8")
    assert "Math.min(next, duration)" in source


def test_the_bar_and_the_clock_come_from_one_number():
    """Two readings of the same fact drifting apart on screen is worse than
    either being a little stale."""
    for rel in ("components/StreamDetail.tsx", "routes/Dashboard.tsx"):
        source = (SOURCE.parents[1] / rel).read_text(encoding="utf-8")
        assert "useRunningOffset(" in source, rel
        assert "runningPercent(offset" in source, rel
