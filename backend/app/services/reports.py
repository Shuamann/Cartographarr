"""Reports: one query builder over everything Cartographarr records.

A report is a source (plays, buffering, rule matches), a measure (how many,
how long, how many different), a dimension to group by and optionally a
second one to split each row by. Every source shares the same dimensions
where it has the data, so "by device" means the same thing for plays and for
buffering, and a new source only has to say which columns it has.

Filters are the same query parameters as the map and History. A filter a
source cannot apply is reported back as ignored rather than silently dropped,
so a report never looks narrower than it is.

Presets are ordinary report specs. Each one is run in the tests, so a preset
cannot rot into an error.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import ColumnElement, and_, case, func, literal, or_, select
from sqlalchemy.orm import Session

from app.filters import Filters, _epoch
from app.models import (
    BandwidthSample,
    Device,
    EnforcementLog,
    History,
    Issue,
    IpLocation,
    Library,
    MediaItem,
    StreamEvent,
    StreamSession,
    User,
)

OTHER = "__other__"
TIME_FORMATS = {
    "day": "%Y-%m-%d",
    "week": "%Y-W%W",
    "month": "%Y-%m",
    "hour": "%H",
    "weekday": "%w",
}
WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    unit: str  # count, hours, minutes, seconds, percent
    expr: Callable[[], ColumnElement]
    hint: str | None = None


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    group: str
    # How the page links a row: user, device, address, media, or nothing.
    kind: str | None = None
    # Shown to viewers only as their own, since it names someone or something they watched.
    identifying: bool = False
    requires: tuple[str, ...] = ()
    hint: str | None = None


@dataclass
class Source:
    key: str
    label: str
    blurb: str
    table: Any
    admin_only: bool
    measures: list[Measure]
    # Dimension key to column expression. A dimension absent here is not offered.
    columns: dict[str, Callable[[], ColumnElement]]
    # Filter name to column, for sources other than plays.
    filter_columns: dict[str, Callable[[], ColumnElement]] = field(default_factory=dict)
    time_column: Callable[[], ColumnElement] | None = None
    epoch_time: bool = False
    joins_location: bool = False
    # For the location and file joins: this source's address and title columns.
    ip_column: Callable[[], ColumnElement] | None = None
    rating_column: Callable[[], ColumnElement] | None = None
    # Rows this source is about, when its table holds more than that. The
    # metadata cache keeps whatever has ever been looked up; the library is
    # only the films and episodes with a file behind them.
    base: Callable[[], ColumnElement[bool]] | None = None


DIMENSIONS: list[Dimension] = [
    Dimension("user", "User", "Who", kind="user", identifying=True),
    Dimension("device", "Device", "Who", kind="device", identifying=True),
    Dimension("player", "Player name", "Who", identifying=True),
    Dimension("platform", "Platform", "Device"),
    Dimension("product", "App", "Device"),
    Dimension("address", "Address", "Where", kind="address", identifying=True),
    Dimension("network", "Network", "Where", identifying=True, requires=("geoip",)),
    Dimension("city", "City", "Where", requires=("geoip",)),
    Dimension("country", "Country", "Where", requires=("geoip",)),
    Dimension("vpn", "VPN or hosting", "Where", requires=("geoip",)),
    Dimension("location", "Local or remote", "Where"),
    Dimension("title", "Title", "What", kind="media", identifying=True),
    Dimension("show", "Show or movie", "What", kind="media", identifying=True,
              hint="Episodes grouped under their show."),
    Dimension("media_type", "Media type", "What"),
    Dimension("library", "Library", "What"),
    Dimension("transcode_decision", "Direct play or transcode", "Quality"),
    Dimension("transcode_cause", "Why it transcoded", "Quality",
              hint="Read from what changed between the file and what was sent. Streams seen live only."),
    Dimension("stream_resolution", "Resolution sent", "Quality"),
    Dimension("hardware", "Hardware transcoding", "Quality"),
    Dimension("stall_cause", "Likely cause", "Quality", hint="Is it the server, the file, or the viewer?"),
    Dimension("file_resolution", "File resolution", "File"),
    Dimension("file_video_codec", "File video format", "File"),
    Dimension("file_hdr", "File HDR", "File"),
    Dimension("file_audio_codec", "File audio format", "File"),
    Dimension("file_bitrate_band", "File bitrate", "File"),
    Dimension("container", "File container", "File"),
    Dimension("year", "Release year", "What"),
    Dimension("played", "Played or never", "What",
              hint="Whether anything has ever been played from the file."),
    Dimension("video_resolution", "Resolution", "Quality"),
    Dimension("quality_profile", "Quality profile", "Quality"),
    Dimension("rule", "Rule", "Rules"),
    Dimension("issue_type", "Kind of problem", "Reports", hint="Video, audio, subtitles or other."),
    Dimension("status", "Open or resolved", "Reports"),
    Dimension("reporter", "Who reported it", "Reports", kind="user", identifying=True),
    Dimension("source", "Reported through", "Reports", hint="Here, or Seerr."),
    Dimension("outcome", "Outcome", "Rules"),
    Dimension("day", "Day", "When"),
    Dimension("week", "Week", "When"),
    Dimension("month", "Month", "When"),
    Dimension("hour", "Hour of day", "When"),
    Dimension("weekday", "Day of week", "When"),
]
DIMENSION = {d.key: d for d in DIMENSIONS}


def _count() -> ColumnElement:
    return func.count()


def _plays() -> ColumnElement:
    """Plays, not sessions: a paused and resumed play counts once."""
    from app.models import History
    from app.plays import plays

    return plays(History)


BITRATE_BANDS = ["Under 5 Mbps", "5 to 10 Mbps", "10 to 20 Mbps", "20 to 40 Mbps", "40 Mbps and up"]


def _bitrate_band(column: Callable[[], ColumnElement] | None = None) -> ColumnElement:
    rate = column() if column else MediaItem.file_bitrate
    return case(
        (rate.is_(None), literal(None)),
        (rate < 5000, literal("1")),
        (rate < 10000, literal("2")),
        (rate < 20000, literal("3")),
        (rate < 40000, literal("4")),
        else_=literal("5"),
    )


def _ever_played() -> ColumnElement:
    """Whether anything has ever been played from this file.

    A correlated exists rather than a join: joining the plays would multiply a
    file by the number of times it was watched, and every size and count in
    the report would come out wrong.
    """
    return select(literal(1)).where(History.rating_key == MediaItem.rating_key).correlate(MediaItem).exists()


# Dimensions read from the file, joined through the title.
FILE_DIMENSIONS = {"file_resolution", "file_video_codec", "file_hdr", "file_audio_codec", "file_bitrate_band"}


SOURCES: dict[str, Source] = {
    "plays": Source(
        key="plays",
        label="Plays",
        blurb="Finished plays synced from Tautulli.",
        table=History,
        admin_only=False,
        joins_location=True,
        epoch_time=True,
        time_column=lambda: History.started,
        measures=[
            Measure("plays", "Plays", "count", _plays),
            Measure("sessions", "Sessions", "count", _count),
            Measure("hours", "Watch time", "hours", lambda: func.coalesce(func.sum(History.play_duration), 0) / 3600.0),
            Measure("users", "Different users", "count", lambda: func.count(func.distinct(History.user_id))),
            Measure("devices", "Different devices", "count", lambda: func.count(func.distinct(History.machine_id))),
            Measure("addresses", "Different addresses", "count", lambda: func.count(func.distinct(History.ip_address))),
            Measure("titles", "Different titles", "count", lambda: func.count(func.distinct(History.rating_key))),
            Measure("transcodes", "Transcoded plays", "count",
                    lambda: func.sum(case((History.transcode_decision == "transcode", 1), else_=0))),
            Measure("completion", "Average completion", "percent", lambda: func.avg(History.percent_complete)),
        ],
        columns={
            "user": lambda: History.user_id,
            "device": lambda: History.machine_id,
            "player": lambda: History.player,
            "platform": lambda: History.platform,
            "product": lambda: History.product,
            "address": lambda: History.ip_address,
            "network": lambda: IpLocation.asn_org,
            "city": lambda: IpLocation.city,
            "country": lambda: IpLocation.country,
            "vpn": lambda: IpLocation.is_hosting,
            "location": lambda: History.location,
            "title": lambda: History.rating_key,
            "show": lambda: func.coalesce(History.grandparent_rating_key, History.rating_key),
            "media_type": lambda: History.media_type,
            "library": lambda: History.section_id,
            "transcode_decision": lambda: History.transcode_decision,
            "file_resolution": lambda: MediaItem.video_resolution,
            "file_video_codec": lambda: MediaItem.video_codec,
            "file_hdr": lambda: MediaItem.video_dynamic_range,
            "file_audio_codec": lambda: MediaItem.audio_codec,
            "file_bitrate_band": _bitrate_band,
        },
        ip_column=lambda: History.ip_address,
        rating_column=lambda: History.rating_key,
    ),
    "buffering": Source(
        key="buffering",
        label="Buffering",
        blurb="Stalls seen while watching live activity. Recorded from the moment this feature was installed.",
        table=StreamEvent,
        admin_only=True,
        joins_location=True,
        time_column=lambda: StreamEvent.started_at,
        measures=[
            Measure("episodes", "Times buffered", "count", _count),
            Measure("minutes", "Time spent buffering", "minutes",
                    lambda: func.coalesce(func.sum(StreamEvent.seconds), 0) / 60.0),
            Measure("average", "Average stall", "seconds", lambda: func.avg(StreamEvent.seconds)),
            Measure("longest", "Longest stall", "seconds", lambda: func.max(StreamEvent.seconds)),
            Measure("streams", "Streams affected", "count", lambda: func.count(func.distinct(StreamEvent.session_key))),
            Measure("users", "Different users", "count", lambda: func.count(func.distinct(StreamEvent.user_id))),
            Measure("devices", "Different devices", "count", lambda: func.count(func.distinct(StreamEvent.machine_id))),
            Measure("bandwidth", "Average bandwidth", "kbps", lambda: func.avg(StreamEvent.bandwidth),
                    hint="Plex's bandwidth estimate for the stream when it stalled."),
        ],
        columns={
            "user": lambda: StreamEvent.user_id,
            "device": lambda: StreamEvent.machine_id,
            "player": lambda: StreamEvent.player,
            "platform": lambda: StreamEvent.platform,
            "product": lambda: StreamEvent.product,
            "address": lambda: StreamEvent.ip_address,
            "network": lambda: IpLocation.asn_org,
            "city": lambda: IpLocation.city,
            "country": lambda: IpLocation.country,
            "vpn": lambda: IpLocation.is_hosting,
            "location": lambda: StreamEvent.location,
            "title": lambda: StreamEvent.rating_key,
            "media_type": lambda: StreamEvent.media_type,
            "transcode_decision": lambda: StreamEvent.transcode_decision,
            "video_resolution": lambda: StreamEvent.video_resolution,
            "quality_profile": lambda: StreamEvent.quality_profile,
            "stall_cause": lambda: StreamEvent.cause,
            "file_resolution": lambda: MediaItem.video_resolution,
            "file_video_codec": lambda: MediaItem.video_codec,
            "file_hdr": lambda: MediaItem.video_dynamic_range,
            "file_audio_codec": lambda: MediaItem.audio_codec,
            "file_bitrate_band": _bitrate_band,
        },
        ip_column=lambda: StreamEvent.ip_address,
        rating_column=lambda: StreamEvent.rating_key,
        filter_columns={
            "user_id": lambda: StreamEvent.user_id,
            "machine_id": lambda: StreamEvent.machine_id,
            "ip_address": lambda: StreamEvent.ip_address,
            "platform": lambda: StreamEvent.platform,
            "product": lambda: StreamEvent.product,
            "player": lambda: StreamEvent.player,
            "media_type": lambda: StreamEvent.media_type,
            "transcode_decision": lambda: StreamEvent.transcode_decision,
            "location": lambda: StreamEvent.location,
            "rating_key": lambda: StreamEvent.rating_key,
            "search": lambda: StreamEvent.full_title,
            "country_code": lambda: IpLocation.country_code,
            "city": lambda: IpLocation.city,
            "is_hosting": lambda: IpLocation.is_hosting,
        },
    ),
    "matches": Source(
        key="matches",
        label="Rule matches",
        blurb="Streams a rule matched or someone stopped by hand, from the Log.",
        table=EnforcementLog,
        admin_only=True,
        time_column=lambda: EnforcementLog.acted_at,
        measures=[
            Measure("matches", "Matches", "count", _count),
            Measure("stopped", "Streams stopped", "count", lambda: func.sum(
                case((and_(EnforcementLog.dry_run.is_(False), EnforcementLog.result.ilike("%terminated%")), 1), else_=0)
            )),
            Measure("recorded", "Recorded only", "count",
                    lambda: func.sum(case((EnforcementLog.dry_run.is_(True), 1), else_=0))),
            Measure("users", "Different users", "count", lambda: func.count(func.distinct(EnforcementLog.user_id))),
            Measure("devices", "Different devices", "count", lambda: func.count(func.distinct(EnforcementLog.machine_id))),
        ],
        columns={
            "user": lambda: EnforcementLog.user_id,
            "device": lambda: EnforcementLog.machine_id,
            "player": lambda: EnforcementLog.player,
            "platform": lambda: EnforcementLog.platform,
            "product": lambda: EnforcementLog.product,
            "address": lambda: EnforcementLog.ip_address,
            "network": lambda: EnforcementLog.asn_org,
            "city": lambda: EnforcementLog.city,
            "country": lambda: EnforcementLog.country,
            "vpn": lambda: EnforcementLog.is_hosting,
            "location": lambda: EnforcementLog.location,
            "title": lambda: EnforcementLog.rating_key,
            "show": lambda: func.coalesce(EnforcementLog.grandparent_rating_key, EnforcementLog.rating_key),
            "media_type": lambda: EnforcementLog.media_type,
            "library": lambda: EnforcementLog.library_name,
            "transcode_decision": lambda: EnforcementLog.transcode_decision,
            "video_resolution": lambda: EnforcementLog.video_resolution,
            "quality_profile": lambda: EnforcementLog.quality_profile,
            "rule": lambda: EnforcementLog.rule_name,
            "outcome": lambda: case(
                (EnforcementLog.dry_run.is_(True), literal("Recorded only")),
                (EnforcementLog.result.ilike("refused%"), literal("Refused")),
                (EnforcementLog.result.ilike("%failed%"), literal("Failed")),
                (EnforcementLog.result.ilike("%terminated%"), literal("Stopped")),
                else_=literal("Acted"),
            ),
        },
        filter_columns={
            "user_id": lambda: EnforcementLog.user_id,
            "machine_id": lambda: EnforcementLog.machine_id,
            "ip_address": lambda: EnforcementLog.ip_address,
            "platform": lambda: EnforcementLog.platform,
            "product": lambda: EnforcementLog.product,
            "player": lambda: EnforcementLog.player,
            "media_type": lambda: EnforcementLog.media_type,
            "transcode_decision": lambda: EnforcementLog.transcode_decision,
            "location": lambda: EnforcementLog.location,
            "rating_key": lambda: EnforcementLog.rating_key,
            "search": lambda: EnforcementLog.full_title,
            "city": lambda: EnforcementLog.city,
            "is_hosting": lambda: EnforcementLog.is_hosting,
        },
    ),
}

SOURCES["streams"] = Source(
    key="streams",
    label="Streams",
    blurb="Every stream seen live: how it played, why it transcoded, and whether it stalled. Recorded from when this version was installed.",
    table=StreamSession,
    admin_only=True,
    joins_location=True,
    time_column=lambda: StreamSession.started_at,
    ip_column=lambda: StreamSession.ip_address,
    rating_column=lambda: StreamSession.rating_key,
    measures=[
        Measure("streams", "Streams", "count", _count),
        Measure("transcoded", "Transcoded", "count",
                lambda: func.sum(case((StreamSession.transcode_decision == "transcode", 1), else_=0))),
        Measure("hardware", "Hardware transcodes", "count",
                lambda: func.sum(case((StreamSession.transcode_hw.is_(True), 1), else_=0))),
        Measure("direct", "Direct plays", "count",
                lambda: func.sum(case((StreamSession.transcode_decision == "direct play", 1), else_=0))),
        Measure("stalled", "Streams that stalled", "count",
                lambda: func.sum(case((StreamSession.buffer_count > 0, 1), else_=0))),
        Measure("stall_minutes", "Time spent stalled", "minutes",
                lambda: func.coalesce(func.sum(StreamSession.buffer_seconds), 0) / 60.0),
        Measure("bandwidth", "Average peak bandwidth", "kbps", lambda: func.avg(StreamSession.bandwidth_max)),
        Measure("users", "Different users", "count", lambda: func.count(func.distinct(StreamSession.user_id))),
    ],
    columns={
        "user": lambda: StreamSession.user_id,
        "device": lambda: StreamSession.machine_id,
        "player": lambda: StreamSession.player,
        "platform": lambda: StreamSession.platform,
        "product": lambda: StreamSession.product,
        "address": lambda: StreamSession.ip_address,
        "network": lambda: IpLocation.asn_org,
        "city": lambda: IpLocation.city,
        "country": lambda: IpLocation.country,
        "vpn": lambda: IpLocation.is_hosting,
        "location": lambda: StreamSession.location,
        "title": lambda: StreamSession.rating_key,
        "show": lambda: func.coalesce(StreamSession.grandparent_rating_key, StreamSession.rating_key),
        "media_type": lambda: StreamSession.media_type,
        "transcode_decision": lambda: StreamSession.transcode_decision,
        "transcode_cause": lambda: StreamSession.primary_cause,
        "stream_resolution": lambda: StreamSession.stream_video_resolution,
        "hardware": lambda: StreamSession.transcode_hw,
        "quality_profile": lambda: StreamSession.quality_profile,
        "file_resolution": lambda: StreamSession.video_resolution,
        "file_video_codec": lambda: StreamSession.video_codec,
        "file_hdr": lambda: StreamSession.video_dynamic_range,
        "file_audio_codec": lambda: StreamSession.audio_codec,
        "file_bitrate_band": lambda: _bitrate_band(lambda: StreamSession.file_bitrate),
    },
    filter_columns={
        "user_id": lambda: StreamSession.user_id,
        "machine_id": lambda: StreamSession.machine_id,
        "ip_address": lambda: StreamSession.ip_address,
        "platform": lambda: StreamSession.platform,
        "product": lambda: StreamSession.product,
        "player": lambda: StreamSession.player,
        "media_type": lambda: StreamSession.media_type,
        "transcode_decision": lambda: StreamSession.transcode_decision,
        "location": lambda: StreamSession.location,
        "rating_key": lambda: StreamSession.rating_key,
        "search": lambda: StreamSession.full_title,
        "country_code": lambda: IpLocation.country_code,
        "city": lambda: IpLocation.city,
        "is_hosting": lambda: IpLocation.is_hosting,
    },
)

SOURCES["server"] = Source(
    key="server",
    label="Server load",
    blurb="Upload and streams, sampled every minute from live activity. Recorded from when this version was installed.",
    table=BandwidthSample,
    admin_only=True,
    epoch_time=True,
    time_column=lambda: BandwidthSample.minute,
    measures=[
        Measure("peak_upload", "Peak upload", "mbps", lambda: func.max(BandwidthSample.wan_kbps) / 1000.0),
        Measure("average_upload", "Average upload", "mbps", lambda: func.avg(BandwidthSample.wan_kbps) / 1000.0,
                hint="Averaged over minutes with anything playing."),
        Measure("peak_streams", "Peak streams", "count", lambda: func.max(BandwidthSample.streams)),
        Measure("peak_remote", "Peak remote streams", "count", lambda: func.max(BandwidthSample.remote_streams)),
        Measure("peak_transcodes", "Peak transcodes", "count", lambda: func.max(BandwidthSample.transcodes)),
        Measure("peak_hardware", "Peak hardware transcodes", "count", lambda: func.max(BandwidthSample.hw_transcodes)),
    ],
    columns={},
)

SOURCES["issues"] = Source(
    key="issues",
    label="Reported problems",
    blurb="What people reported was wrong, raised here or in Seerr. Counts the report, not the file.",
    table=Issue,
    admin_only=True,
    time_column=lambda: Issue.created_at,
    measures=[
        Measure("reports", "Reports", "count", _count),
        Measure("open", "Still open", "count",
                lambda: func.sum(case((Issue.status == "open", 1), else_=0))),
        Measure("resolved", "Resolved", "count",
                lambda: func.sum(case((Issue.status == "resolved", 1), else_=0))),
        Measure("titles", "Different titles", "count", lambda: func.count(func.distinct(Issue.rating_key))),
        Measure("people", "Different people", "count", lambda: func.count(func.distinct(Issue.reporter_user_id))),
    ],
    columns={
        # What went wrong, who said so, and what it was about: the three
        # questions a pile of reports should answer.
        "issue_type": lambda: Issue.issue_type,
        "status": lambda: Issue.status,
        "reporter": lambda: Issue.reporter_user_id,
        "source": lambda: Issue.source,
        "media_type": lambda: Issue.media_type,
        "title": lambda: Issue.rating_key,
        "show": lambda: func.coalesce(Issue.show_rating_key, Issue.rating_key),
    },
    filter_columns={
        "user_id": lambda: Issue.reporter_user_id,
        "media_type": lambda: Issue.media_type,
        "rating_key": lambda: Issue.rating_key,
        "search": lambda: Issue.title,
    },
)

SOURCES["library"] = Source(
    key="library",
    label="Library",
    blurb="What is on the disks now, from the library scan. A snapshot rather than a history, so the dates do not apply.",
    table=MediaItem,
    admin_only=True,
    # Films and episodes with a file. The rest of this table is metadata
    # looked up for other reasons, with no size, no bitrate and no disk.
    base=lambda: MediaItem.media_type.in_(("movie", "episode")),
    measures=[
        Measure("items", "Files", "count", _count),
        Measure("size", "Space used", "bytes", lambda: func.coalesce(func.sum(MediaItem.file_size), 0)),
        Measure("average_size", "Average file", "bytes", lambda: func.avg(MediaItem.file_size)),
        Measure("hours", "Running time", "hours",
                lambda: func.coalesce(func.sum(MediaItem.duration), 0) / 3_600_000.0),
        Measure("bitrate", "Average bitrate", "kbps", lambda: func.avg(MediaItem.file_bitrate),
                hint="Averaged over the files that have been checked."),
        Measure("never_played", "Never played", "count",
                lambda: func.sum(case((_ever_played(), 0), else_=1)),
                hint="Files with no play recorded against them, ever."),
        Measure("shows", "Different shows", "count", lambda: func.count(func.distinct(
            func.coalesce(MediaItem.grandparent_rating_key, MediaItem.rating_key)))),
    ],
    columns={
        "library": lambda: MediaItem.section_id,
        "media_type": lambda: MediaItem.media_type,
        "title": lambda: MediaItem.rating_key,
        "show": lambda: func.coalesce(MediaItem.grandparent_rating_key, MediaItem.rating_key),
        "year": lambda: MediaItem.year,
        "played": lambda: case((_ever_played(), literal("played")), else_=literal("never")),
        "file_resolution": lambda: MediaItem.video_resolution,
        "file_video_codec": lambda: MediaItem.video_codec,
        "file_hdr": lambda: MediaItem.video_dynamic_range,
        "file_audio_codec": lambda: MediaItem.audio_codec,
        "file_bitrate_band": _bitrate_band,
        "container": lambda: MediaItem.file_container,
    },
    filter_columns={
        "section_id": lambda: MediaItem.section_id,
        "media_type": lambda: MediaItem.media_type,
        "rating_key": lambda: MediaItem.rating_key,
        "search": lambda: MediaItem.full_title,
    },
)

# Starting points. Ordinary specs: open one, change it, save it as your own.
PRESETS: list[dict[str, Any]] = [
    {"id": "issues-kind", "name": "Reports by kind", "source": "issues", "measure": "reports",
     "group": "issue_type", "then": "status", "range": "90"},
    {"id": "issues-title", "name": "Most reported titles", "source": "issues", "measure": "reports",
     "group": "title", "then": "issue_type", "range": "365"},
    {"id": "buffering-device", "name": "Buffering by device", "source": "buffering", "measure": "episodes",
     "group": "device", "then": "transcode_decision", "range": "30"},
    {"id": "buffering-network", "name": "Buffering by network", "source": "buffering", "measure": "minutes",
     "group": "network", "then": None, "range": "30"},
    {"id": "buffering-user", "name": "Buffering by user", "source": "buffering", "measure": "episodes",
     "group": "user", "then": "video_resolution", "range": "30"},
    {"id": "buffering-daily", "name": "Buffering per day", "source": "buffering", "measure": "episodes",
     "group": "day", "then": None, "range": "30"},
    {"id": "watch-time-user", "name": "Watch time by user", "source": "plays", "measure": "hours",
     "group": "user", "then": "media_type", "range": "30"},
    {"id": "plays-hour", "name": "When people watch", "source": "plays", "measure": "plays",
     "group": "hour", "then": None, "range": "90"},
    {"id": "transcodes-device", "name": "Transcodes by device", "source": "plays", "measure": "plays",
     "group": "device", "then": "transcode_decision", "range": "30"},
    {"id": "top-shows", "name": "Most watched", "source": "plays", "measure": "hours",
     "group": "show", "then": None, "range": "30"},
    {"id": "vpn-users", "name": "Plays from VPNs, by user", "source": "plays", "measure": "plays",
     "group": "user", "then": "network", "range": "90", "filters": "is_hosting=true"},
    {"id": "matches-rule", "name": "Rule matches by rule", "source": "matches", "measure": "matches",
     "group": "rule", "then": "outcome", "range": "30"},
    {"id": "stall-causes", "name": "Is it me or them?", "source": "buffering", "measure": "episodes",
     "group": "stall_cause", "then": None, "range": "30"},
    {"id": "transcode-causes", "name": "Why streams transcode", "source": "streams", "measure": "transcoded",
     "group": "transcode_cause", "then": "platform", "range": "30"},
    {"id": "upload-hour", "name": "Upload by hour", "source": "server", "measure": "peak_upload",
     "group": "hour", "then": None, "range": "30"},
    {"id": "upload-day", "name": "Busiest days", "source": "server", "measure": "peak_upload",
     "group": "day", "then": None, "range": "90"},
    {"id": "plays-file-bitrate", "name": "Plays by file bitrate", "source": "plays", "measure": "plays",
     "group": "file_bitrate_band", "then": "transcode_decision", "range": "90"},
    {"id": "library-space", "name": "Space by library", "source": "library", "measure": "size",
     "group": "library", "then": "file_resolution", "range": "all"},
    {"id": "library-unplayed", "name": "What has never been played", "source": "library", "measure": "items",
     "group": "library", "then": "played", "range": "all"},
    {"id": "library-resolution", "name": "Files by resolution", "source": "library", "measure": "items",
     "group": "file_resolution", "then": "media_type", "range": "all"},
    {"id": "library-container", "name": "Container and codec mix", "source": "library", "measure": "items",
     "group": "container", "then": "file_video_codec", "range": "all"},
    {"id": "library-shows", "name": "Space by show", "source": "library", "measure": "size",
     "group": "show", "then": None, "range": "all"},
]


def catalog(*, admin: bool, geoip: bool) -> dict[str, Any]:
    """What the builder can offer this person."""
    sources = []
    for s in SOURCES.values():
        if s.admin_only and not admin:
            continue
        dims = [d for d in DIMENSIONS if d.key in s.columns or (d.key in TIME_FORMATS and s.time_column)]
        sources.append({
            "key": s.key,
            "label": s.label,
            "blurb": s.blurb,
            "measures": [{"key": m.key, "label": m.label, "unit": m.unit, "hint": m.hint} for m in s.measures],
            "dimensions": [
                {
                    "key": d.key, "label": d.label, "group": d.group, "kind": d.kind, "hint": d.hint,
                    "unavailable": ("Needs GeoIP set up" if "geoip" in d.requires and not geoip else None),
                }
                for d in dims
            ],
        })
    allowed = {s["key"] for s in sources}
    return {"sources": sources, "presets": [p for p in PRESETS if p["source"] in allowed]}


def validate(source: str, measure: str, group: str, then: str | None) -> Source:
    s = SOURCES.get(source)
    if s is None:
        raise ValueError(f"No report source called {source!r}")
    if not any(m.key == measure for m in s.measures):
        raise ValueError(f"{s.label} has no measure called {measure!r}")
    for dim in (group, then):
        if dim is None:
            continue
        if dim not in s.columns and not (dim in TIME_FORMATS and s.time_column):
            raise ValueError(f"{s.label} cannot be grouped by {dim!r}")
    if then is not None and then == group:
        raise ValueError("Split by must be different from group by")
    return s


def _dimension_expr(s: Source, key: str) -> ColumnElement:
    if key in TIME_FORMATS:
        assert s.time_column is not None
        if s.epoch_time:
            return func.strftime(TIME_FORMATS[key], s.time_column(), "unixepoch", "localtime")
        return func.strftime(TIME_FORMATS[key], s.time_column(), "localtime")
    return s.columns[key]()


def _where(s: Source, filters: Filters) -> tuple[list[ColumnElement[bool]], list[str], bool]:
    """Predicates for the filters, the filters that could not apply, and
    whether the location table is needed."""
    if s.key == "plays":
        return filters.conditions(), [], filters.needs_location_join

    where: list[ColumnElement[bool]] = []
    ignored: list[str] = []
    needs_location = False
    time_col = s.time_column() if s.time_column else None

    def moment(epoch: int):
        return epoch if s.epoch_time else datetime.fromtimestamp(epoch, UTC)

    if time_col is None:
        # A snapshot has no clock. Saying so beats a report that quietly covers
        # everything while the page shows a thirty day range.
        if filters.start or filters.end:
            ignored.append("dates")
    else:
        if filters.start:
            where.append(time_col >= moment(_epoch(filters.start)))
        if filters.end:
            where.append(time_col < moment(_epoch(filters.end) + 86400))

    for name in (
        "user_id", "machine_id", "ip_address", "platform", "product", "player", "media_type",
        "transcode_decision", "section_id", "country_code",
    ):
        values = getattr(filters, name)
        if not values:
            continue
        column = s.filter_columns.get(name)
        if column is None:
            ignored.append(name)
            continue
        col = column()
        needs_location |= getattr(col, "table", None) is IpLocation.__table__
        where.append(col.in_(values))

    for name in ("location", "city", "search", "is_hosting", "rating_key"):
        value = getattr(filters, name)
        if value is None or value == "":
            continue
        column = s.filter_columns.get(name)
        if column is None:
            ignored.append(name)
            continue
        col = column()
        needs_location |= getattr(col, "table", None) is IpLocation.__table__
        if name in ("city", "search"):
            where.append(col.ilike(f"%{value}%"))
        elif name == "is_hosting":
            where.append(col.is_(value))
        else:
            where.append(col == value)

    for name in ("secure", "relayed", "watched"):
        if getattr(filters, name) is not None:
            ignored.append(name)
    return where, ignored, needs_location


def _base(s: Source, columns: list[ColumnElement], where: list, needs_location: bool, needs_media: bool = False):
    stmt = select(*columns).select_from(s.table)
    if s.base is not None:
        stmt = stmt.where(s.base())
    if needs_location and s.joins_location and s.ip_column is not None:
        stmt = stmt.outerjoin(IpLocation, IpLocation.ip == s.ip_column())
    if needs_media and s.rating_column is not None:
        stmt = stmt.outerjoin(MediaItem, MediaItem.rating_key == s.rating_column())
    if where:
        stmt = stmt.where(*where)
    return stmt


def run(
    db: Session,
    filters: Filters,
    *,
    source: str,
    measure: str,
    group: str,
    then: str | None = None,
    limit: int = 25,
    columns_limit: int = 8,
) -> dict[str, Any]:
    s = validate(source, measure, group, then)
    m = next(x for x in s.measures if x.key == measure)
    where, ignored, needs_location = _where(s, filters)
    uses_location = any(
        d in ("network", "city", "country", "vpn") for d in (group, then) if d
    ) and s.joins_location
    needs_location = needs_location or uses_location
    # Streams keep their own copy of the file's details, and the library source
    # is that table already, so neither of them joins it.
    needs_media = s.table not in (StreamSession, MediaItem) and any(
        d in FILE_DIMENSIONS for d in (group, then) if d
    )

    is_time = group in TIME_FORMATS
    g = _dimension_expr(s, group).label("grp")
    value = m.expr().label("val")

    # Row totals come from their own grouping, not by adding up the split, since
    # averages and "different" counts do not add up.
    stmt = _base(s, [g, value], where, needs_location, needs_media).group_by(g)
    stmt = stmt.order_by(g) if is_time else stmt.order_by(value.desc(), g)
    rows = db.execute(stmt).all()
    truncated = False
    if not is_time and len(rows) > limit:
        rows, truncated = rows[:limit], True

    grand = db.execute(_base(s, [m.expr().label("val")], where, needs_location, needs_media)).scalar()

    result_rows = [{"key": r.grp, "value": _num(r.val)} for r in rows]
    columns: list[dict[str, Any]] = []
    if then:
        t = _dimension_expr(s, then).label("split")
        t_is_time = then in TIME_FORMATS
        col_stmt = _base(s, [t, m.expr().label("val")], where, needs_location, needs_media).group_by(t)
        col_stmt = col_stmt.order_by(t) if t_is_time else col_stmt.order_by(m.expr().desc(), t)
        col_rows = db.execute(col_stmt).all()
        kept = [r.split for r in (col_rows if t_is_time else col_rows[:columns_limit])]
        has_other = not t_is_time and len(col_rows) > columns_limit
        columns = [{"key": k} for k in kept] + ([{"key": OTHER}] if has_other else [])

        cell_stmt = _base(s, [g, t, m.expr().label("val")], where, needs_location, needs_media).group_by(g, t)
        cells: dict[Any, dict[Any, float]] = {}
        additive = _additive(m)
        kept_set = set(kept)
        for r in db.execute(cell_stmt).all():
            gk, tk = r.grp, r.split
            bucket = tk if tk in kept_set else OTHER
            row = cells.setdefault(gk, {})
            if bucket == OTHER:
                # "Other" can only be summed for additive measures. For the
                # rest it is left out rather than shown wrong.
                if additive:
                    row[OTHER] = row.get(OTHER, 0) + (_num(r.val) or 0)
            else:
                row[bucket] = _num(r.val)
        if has_other and not additive:
            columns = [c for c in columns if c["key"] != OTHER]
        for row in result_rows:
            row["cells"] = cells.get(row["key"], {})

    if is_time:
        result_rows = _fill_gaps(group, result_rows, _additive(m))

    labels = _labels(db, group, [r["key"] for r in result_rows])
    for row in result_rows:
        row["label"] = labels.get(row["key"], _plain_label(group, row["key"]))
    if then:
        col_labels = _labels(db, then, [c["key"] for c in columns])
        for c in columns:
            c["label"] = "Other" if c["key"] == OTHER else col_labels.get(c["key"], _plain_label(then, c["key"]))

    dim = DIMENSION[group]
    return {
        "source": s.key,
        "measure": {"key": m.key, "label": m.label, "unit": m.unit, "additive": _additive(m)},
        "group": {"key": dim.key, "label": dim.label, "kind": dim.kind, "time": is_time},
        "then": None if not then else {"key": then, "label": DIMENSION[then].label, "kind": DIMENSION[then].kind},
        "rows": result_rows,
        "columns": columns,
        "total": _num(grand),
        "truncated": truncated,
        "ignored": ignored,
    }


def _fill_gaps(dim: str, rows: list[dict[str, Any]], additive: bool) -> list[dict[str, Any]]:
    """Time with nothing in it still gets a row, so a chart does not close up
    the quiet hours or days and make the busy ones look adjacent."""
    empty = 0 if additive else None
    have = {r["key"]: r for r in rows}
    if dim == "hour":
        keys = [f"{h:02d}" for h in range(24)]
    elif dim == "weekday":
        keys = [str(d) for d in range(7)]
    elif dim == "day" and rows:
        first = datetime.strptime(rows[0]["key"], "%Y-%m-%d").date()
        last = datetime.strptime(rows[-1]["key"], "%Y-%m-%d").date()
        if (last - first).days > 3660:
            return rows
        keys = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    else:
        return rows
    filler = {"cells": {}} if rows and "cells" in rows[0] else {}
    return [have.get(k) or {"key": k, "value": empty, **filler} for k in keys]


def _additive(m: Measure) -> bool:
    """Whether parts add up to the whole. Sums and counts do; averages, maxima
    and counts of different things do not."""
    return m.unit in ("count", "hours", "minutes", "bytes") and m.key not in (
        "users", "devices", "addresses", "titles", "streams", "shows", "average_size", "average",
    )


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    f = float(value)
    return int(f) if f.is_integer() else round(f, 2)


def _plain_label(dim: str, key: Any) -> str:
    if key is None or key == "":
        return {
            "vpn": "Not looked up",
            "location": "Unknown",
            "transcode_cause": "Not transcoded",
            "stall_cause": "Not worked out yet",
            "file_bitrate_band": "File not checked yet",
            "hardware": "Software or none",
            "container": "Not checked yet",
            "year": "No year",
        }.get(dim, "Unknown")
    if dim == "vpn":
        return "VPN or hosting" if key in (True, 1, "1") else "Home or mobile network"
    if dim == "location":
        return {"lan": "Local", "wan": "Remote"}.get(str(key), str(key))
    if dim == "hour":
        return f"{int(key):02d}:00"
    if dim == "weekday":
        return WEEKDAYS[int(key)]
    if dim == "file_bitrate_band":
        return BITRATE_BANDS[int(key) - 1] if str(key).isdigit() and 1 <= int(key) <= 5 else str(key)
    if dim == "hardware":
        return "Hardware" if key in (True, 1, "1") else "Software or none"
    if dim == "played":
        return "Played at least once" if str(key) == "played" else "Never played"
    if dim == "transcode_cause":
        from app.services.streams import CAUSES as TRANSCODE_CAUSES

        return TRANSCODE_CAUSES.get(str(key), str(key))
    if dim == "stall_cause":
        from app.services.stalls import CAUSES as STALL_CAUSES

        return STALL_CAUSES.get(str(key), str(key))
    if dim == "transcode_decision":
        return {"direct play": "Direct play", "copy": "Direct stream", "transcode": "Transcode"}.get(str(key), str(key))
    return str(key)


def _labels(db: Session, dim: str, keys: list[Any]) -> dict[Any, str]:
    """Names for ids: users, devices, libraries and titles."""
    present = [k for k in keys if k not in (None, OTHER)]
    if not present:
        return {}
    if dim == "user":
        rows = db.execute(select(User.user_id, User.friendly_name, User.username).where(User.user_id.in_(present))).all()
        return {r.user_id: r.friendly_name or r.username or f"User {r.user_id}" for r in rows}
    if dim == "device":
        rows = db.execute(
            select(Device.machine_id, Device.player, Device.platform)
            .where(Device.machine_id.in_(present))
            .order_by(Device.last_seen.desc())
        ).all()
        out: dict[Any, str] = {}
        for r in rows:
            out.setdefault(r.machine_id, f"{r.player or r.machine_id}{f' ({r.platform})' if r.platform else ''}")
        return out
    if dim == "library":
        ints = [k for k in present if isinstance(k, int)]
        rows = db.execute(select(Library.section_id, Library.name).where(Library.section_id.in_(ints))).all()
        return {r.section_id: r.name or f"Library {r.section_id}" for r in rows}
    if dim in ("title", "show"):
        ints = [int(k) for k in present if str(k).isdigit()]
        rows = db.execute(select(MediaItem.rating_key, MediaItem.full_title, MediaItem.title).where(
            MediaItem.rating_key.in_(ints)
        )).all()
        found = {r.rating_key: (r.full_title or r.title) for r in rows}
        if dim == "title":
            # Episodes read with their number, as everywhere else.
            for r in db.execute(
                select(History.rating_key, History.grandparent_title, History.title,
                       History.parent_media_index, History.media_index)
                .where(History.rating_key.in_(ints), History.media_index.is_not(None),
                       History.parent_media_index.is_not(None))
                .group_by(History.rating_key)
            ).all():
                found[r.rating_key] = " - ".join(
                    x for x in (r.grandparent_title, f"S{r.parent_media_index:02d}E{r.media_index:02d}", r.title) if x
                )
        # Titles not in the metadata cache fall back to what the play recorded.
        missing = [k for k in ints if not found.get(k)]
        if missing:
            for r in db.execute(
                select(History.rating_key, History.grandparent_rating_key, History.full_title, History.title)
                .where(or_(History.rating_key.in_(missing), History.grandparent_rating_key.in_(missing)))
            ).all():
                if r.rating_key in missing and not found.get(r.rating_key):
                    found[r.rating_key] = r.full_title or r.title
                if dim == "show" and r.grandparent_rating_key in missing and not found.get(r.grandparent_rating_key):
                    full = r.full_title or ""
                    found[r.grandparent_rating_key] = full.split(" - ")[0] if " - " in full else full
        return {k: v for k, v in found.items() if v}
    return {}
