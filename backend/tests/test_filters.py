from datetime import date, datetime

from app.filters import Filters, _epoch


def test_epoch_is_local_midnight():
    # strftime("%s") is glibc-only and absent on Windows; this is the guard.
    day = date(2026, 3, 14)
    assert _epoch(day) == int(datetime(2026, 3, 14, 0, 0, 0).timestamp())


def test_no_filters_means_no_conditions():
    assert Filters().conditions() == []


def test_end_date_covers_the_whole_day():
    day = date(2026, 3, 14)
    conditions = Filters(end=day).conditions()
    assert len(conditions) == 1
    # Upper bound is the start of the 15th, so plays at 23:59 on the 14th count.
    assert str(_epoch(day) + 86400) in str(conditions[0].compile(
        compile_kwargs={"literal_binds": True}
    ))


def test_location_join_only_when_a_location_filter_is_set():
    assert Filters().needs_location_join is False
    assert Filters(platform=["Roku"]).needs_location_join is False
    assert Filters(country_code=["US"]).needs_location_join is True
    assert Filters(is_hosting=True).needs_location_join is True


def test_rating_key_matches_show_season_and_episode():
    # Picking a series on the map has to surface every episode's plays.
    conditions = Filters(rating_key=42).conditions()
    sql = str(conditions[0].compile(compile_kwargs={"literal_binds": True}))
    assert "rating_key = 42" in sql
    assert "parent_rating_key = 42" in sql
    assert "grandparent_rating_key = 42" in sql
