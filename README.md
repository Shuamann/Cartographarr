# Cartographarr

Maps Plex viewing history by location, and enforces device-level access control,
on top of Tautulli.

Plex has no API to ban a shared user's device — `plex.tv/devices.xml` only lists
devices on the token owner's own account, so a friend's Firestick is invisible to
you. Blocking is therefore behavioural: match the live session on `machine_id`
(Plex's `clientIdentifier`, stable across player renames) and terminate it.

## Status

Backend through the read API. Map data, filters, stats and media deep links work.
No UI yet — use `/docs`.

## Configure

Copy `backend/.env.example` to `backend/.env` and fill it in. Both the container
and local development read that one file.

| Setting | Required | Notes |
|---|---|---|
| `TAUTULLI_URL` | yes | Remote/fallback URL |
| `TAUTULLI_API_KEY` | yes | Tautulli → Settings → Web Interface |
| `TAUTULLI_LOCAL_URL` | no | LAN address, preferred when reachable. Tried once with a short timeout, then it falls back for the life of the process |
| `MAXMIND_ACCOUNT_ID` + `MAXMIND_LICENSE_KEY` | for the map | Free GeoLite2 account. Without them there are no pins |
| `PLEX_MACHINE_IDENTIFIER` | no | Enables the Plex deep-link button |

**Anything set as an environment variable wins and shows read-only in the UI.**
Leave a key out entirely and the UI owns it, saving to the database — the way
Radarr behaves. A newly issued MaxMind key can take a few minutes to work.

## Run on Unraid

```bash
docker compose up -d --build
```

Serves on `:8420`, data in `/mnt/user/appdata/cartographarr`. Runs as `99:100`
(nobody:users) to match Unraid's appdata ownership.

To use Unraid's Docker template UI instead of compose, set the same variables as
container env vars, map `/data` to `/mnt/user/appdata/cartographarr`, and publish
container port 8000.

The first sync backfills all history — roughly 3 minutes for 14k plays, almost
entirely one-time metadata fetching. After that a cycle with no new plays costs
about a tenth of a second.

## Develop

```bash
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]" && .venv/Scripts/python -m pytest -q
```

Confirm which data source your Tautulli supports:

```bash
cd backend && .venv/Scripts/python -m scripts.probe_source
```

## Design notes

- **Sync moves only the delta.** A watermark bounds the history pull, each IP is
  geocoded once ever, each `rating_key` fetched once ever. Items deleted from
  Plex get a tombstone row, otherwise they are re-requested on every sync forever.
- **`get_stream_data` is never synced.** Codec/bitrate/resolution need a per-row
  call, and rules read live `get_activity` which already carries them. Stream
  detail fetches on demand, so nothing pays for rows nobody opens.
- **Hosting/VPN detection excludes residential markers first.** `Google Fiber` is
  an ISP, not a datacentre; matching `google` alone made 94% of flags false
  positives on real data.
- **One filter model.** `app/filters.py` feeds the map, history and stats alike,
  so a filter added once works everywhere.
