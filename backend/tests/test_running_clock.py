import pathlib

SOURCE = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "playing.ts"


def test_it_only_runs_while_the_stream_is_playing():
    source = SOURCE.read_text(encoding="utf-8")
    assert "if (!playing) return;" in source, "a paused stream must not keep climbing"


def test_the_server_replaces_the_guess_rather_than_being_averaged_into_it():
    source = SOURCE.read_text(encoding="utf-8")
    assert "told.current = { offset, at: Date.now() };" in source
    assert "setShown(offset);" in source


def test_it_never_runs_past_the_end():
    source = SOURCE.read_text(encoding="utf-8")
    assert "Math.min(next, duration)" in source


def test_the_bar_and_the_clock_come_from_one_number():
    for rel in ("components/StreamDetail.tsx", "routes/Dashboard.tsx"):
        source = (SOURCE.parents[1] / rel).read_text(encoding="utf-8")
        assert "useRunningOffset(" in source, rel
        assert "runningPercent(offset" in source, rel
