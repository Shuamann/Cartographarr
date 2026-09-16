#!/usr/bin/env python3
"""Probe: does get_history return machine_id?

machine_id (== Plex's clientIdentifier) is the key every device rule matches
on. It is a column of Tautulli's session_history table, but the documented
get_history API response does not list it. This settles which source the sync
layer uses, and nothing else gets built until it answers.

    api  -> machine_id is right there. Use the API. Done.
    enrich -> absent from get_history, but get_stream_data(row_id) has it.
              API source + a per-new-row enrichment call.
    db   -> neither. Fall back to snapshotting Tautulli's SQLite.

Run:  python -m scripts.probe_source
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.config import get_settings
from app.tautulli.client import TautulliClient

WANTED = [
    "machine_id",
    "row_id",
    "reference_id",
    "user_id",
    "ip_address",
    "platform",
    "player",
    "product",
    "transcode_decision",
    "video_resolution",
    "location",
    "secure",
    "relayed",
    "bandwidth",
    "quality_profile",
    "section_id",
    "rating_key",
]


async def main() -> int:
    client = TautulliClient(get_settings())
    try:
        data = await client.call("get_history", length=1, order_column="date", order_dir="desc")
        rows = (data or {}).get("data") or []
        if not rows:
            print("No history rows returned. Is this server new, or the key wrong?")
            return 2
        row = rows[0]

        print(f"get_history returned {len(row)} fields:\n")
        print(json.dumps(sorted(row.keys()), indent=2))

        print("\nFields the sync layer wants:")
        for field in WANTED:
            mark = "OK  " if field in row else "MISS"
            print(f"  [{mark}] {field}")

        if "machine_id" in row:
            print("\n=> SOURCE_MODE=api. machine_id is in get_history.")
            return 0

        # Not in get_history. get_stream_data is the cheaper fallback than
        # snapshotting the whole DB, so check it before giving up on the API.
        row_id = row.get("row_id") or row.get("id")
        if row_id is not None:
            stream = await client.call("get_stream_data", row_id=row_id) or {}
            print(f"\nget_stream_data({row_id}) fields:\n")
            print(json.dumps(sorted(stream.keys()), indent=2))
            if "machine_id" in stream:
                print("\n=> SOURCE_MODE=api + per-row get_stream_data enrichment.")
                return 0

        print("\n=> SOURCE_MODE=db. Neither call exposes machine_id; use the")
        print("   snapshot fallback (copy db+wal+shm, open the COPY read-write).")
        return 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
