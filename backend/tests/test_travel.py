"""Impossible travel.

This decides whether someone gets accused of sharing their password, so the
cases that matter most are the ones that must NOT flag. GeoLite2 states an
error of anywhere from 5 km to 1000 km, and a naive distance check would flag
half a library.
"""

from app.services.travel import CONCURRENT_WINDOW_SECONDS, haversine_km


def test_haversine_matches_known_distances():
    # Topeka to Seattle, about 2,350 km.
    km = haversine_km(39.0558, -95.6894, 47.6062, -122.3321)
    assert 2250 < km < 2450

    # London to Paris, about 344 km.
    km = haversine_km(51.5072, -0.1276, 48.8566, 2.3522)
    assert 330 < km < 360


def test_haversine_is_zero_for_the_same_point():
    assert haversine_km(39.0, -95.0, 39.0, -95.0) == 0


def test_haversine_is_symmetric():
    there = haversine_km(39.0558, -95.6894, 47.6062, -122.3321)
    back = haversine_km(47.6062, -122.3321, 39.0558, -95.6894)
    assert abs(there - back) < 0.001


def test_concurrent_window_is_generous_enough_to_matter():
    # The window exists because two plays seconds apart are simultaneous, not
    # a journey. Without it the speed divides by almost nothing and reports
    # figures like a million kilometres an hour.
    assert CONCURRENT_WINDOW_SECONDS >= 60


def speed(km: float, seconds: float) -> float:
    return km / (seconds / 3600)


def test_the_thresholds_separate_real_travel_from_flights():
    # A commercial flight, Topeka to Seattle in three hours, is ordinary.
    assert speed(2346, 3 * 3600) < 900
    # The same trip in one hour is not.
    assert speed(2346, 1 * 3600) > 900


def test_a_short_hop_stays_under_the_distance_floor():
    # Two neighbouring towns can differ by tens of kilometres purely from
    # centroid error, which is why there is a 100 km floor.
    assert haversine_km(39.0558, -95.6894, 39.1836, -96.5717) < 100
