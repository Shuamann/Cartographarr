"""Live activity read from Plex instead of from Tautulli.

The shape has to match Tautulli's field for field, because the tracker, the
rules, the ban list, the map and the stream cards all read that shape. The one
word that matters most is the transcode decision: every rule anybody has
written matches on it, and Plex answers per stream where this app wants one
answer for the session.
"""

from types import SimpleNamespace

from app.plex import activity


def a_player(**over):
    base = dict(
        machineIdentifier="ktk6", title="Chrome", platform="Chrome", product="Plex Web",
        device="Windows", address="203.0.113.75", remotePublicAddress="203.0.113.75",
        local=False, secure=True, relayed=False, state="playing", userID=77000001,
    )
    return SimpleNamespace(**{**base, **over})


def a_session(transcode=None, player=None, **over):
    media = SimpleNamespace(
        container="mkv", videoResolution="1080", bitrate=5639,
        videoCodec="hevc", audioCodec="eac3", parts=[SimpleNamespace(streams=[])],
    )
    base = dict(
        sessionKey="42", user=SimpleNamespace(id=77000001, title="Casey", username="casey_h", thumb=None),
        usernames=["casey_h"], players=[player or a_player()], media=[media],
        transcodeSession=transcode, session=SimpleNamespace(id="s1", bandwidth=5639),
        type="episode", title="Indescribable Compassion", grandparentTitle="The Chosen",
        parentTitle="Season 1", index=3, parentIndex=1, year=2023, ratingKey=63424,
        grandparentRatingKey=63000, librarySectionID=2, librarySectionTitle="TV",
        duration=3114112, viewOffset=124564, thumb=None, art=None, summary=None,
        contentRating=None, originallyAvailableAt=None,
    )
    return SimpleNamespace(**{**base, **over})


def test_everything_a_stream_is_recorded_by_is_there():
    s = activity._session(a_session())
    # The id is the Plex account id, which is what this app files everything
    # under: a ban, a privacy scope and four years of history all key on it.
    assert s["user_id"] == 77000001
    assert s["machine_id"] == "ktk6"
    # The reason this is possible at all.
    assert s["ip_address"] == "203.0.113.75"
    assert s["location"] == "wan" and s["secure"] is True and s["relayed"] is False
    assert s["state"] == "playing"
    assert s["rating_key"] == 63424 and s["section_id"] == 2
    assert s["full_title"] == "The Chosen - Indescribable Compassion"
    assert s["progress_percent"] == 4


def test_a_local_viewer_reads_as_local():
    s = activity._session(a_session(player=a_player(local=True)))
    assert s["location"] == "lan"


def test_nothing_being_converted_is_a_direct_play():
    assert activity._session(a_session())["transcode_decision"] == "direct play"


def test_audio_alone_being_converted_is_still_a_transcode():
    """The case that caught this out against a real stream: video copied,
    audio converted from eac3 to aac. Tautulli calls that a transcode, every
    rule written here matches on that word, and reading the video decision
    alone would have called it a copy and quietly stopped those rules firing.
    """
    ts = SimpleNamespace(videoDecision="copy", audioDecision="transcode",
                         subtitleDecision=None, container="mp4", speed=1.0, throttled=True,
                         videoCodec="hevc", audioCodec="aac")
    s = activity._session(a_session(transcode=ts))
    assert s["transcode_decision"] == "transcode"
    assert s["video_decision"] == "copy" and s["audio_decision"] == "transcode"


def test_a_remux_is_a_copy_and_not_a_transcode():
    ts = SimpleNamespace(videoDecision="copy", audioDecision="copy", subtitleDecision=None,
                         container="mp4", speed=None, throttled=False, videoCodec="hevc", audioCodec="eac3")
    assert activity._session(a_session(transcode=ts))["transcode_decision"] == "copy"


def test_the_shape_matches_what_tautulli_returns():
    """Everything below this reads Tautulli's field names. A missing one is a
    blank on a card rather than an error, which is worse."""
    from app.routers import live as live_router

    s = activity._session(a_session())
    missing = [f for f in live_router.SESSION_FIELDS if f not in s]
    assert not missing, f"fields the rest of the app expects and Plex is not filling: {missing}"
