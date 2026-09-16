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

## Install

```bash
docker compose up -d --build
```

Serves on `:8420`, data in `/mnt/user/appdata/cartographarr`, running as
`99:100` (nobody:users) to match Unraid's appdata ownership. On Unraid's Docker
template UI instead: map `/data` to your appdata path and publish container
port 8000.

**No configuration needed to start.** The container boots unconfigured and the
UI walks you through first-run setup — Tautulli URL and API key, optionally a
free MaxMind GeoLite2 account for the map. Credentials are validated before
they're saved, stored in the app's own database, and editable afterwards in
Settings. Nothing is baked into the image.

The first sync backfills your whole history. Expect a few minutes on a large
library, almost entirely one-time metadata fetching; after that a cycle with no
new plays costs about a tenth of a second.

### Configuring by environment variable instead

Every setting can also be supplied as an env var, which is handy for Unraid
templates. **An environment variable wins and renders read-only in the UI** —
exactly how Radarr behaves. Leave one unset and the UI owns it.

| Variable | Notes |
|---|---|
| `TAUTULLI_URL` | Remote/fallback URL |
| `TAUTULLI_API_KEY` | Tautulli → Settings → Web Interface |
| `TAUTULLI_LOCAL_URL` | LAN address, preferred when reachable. Tried once with a short timeout, then it falls back for the life of the process |
| `MAXMIND_ACCOUNT_ID`, `MAXMIND_LICENSE_KEY` | Free GeoLite2 account. Without them there are no map pins |
| `PLEX_MACHINE_IDENTIFIER` | Enables the Plex deep-link button |

A newly issued MaxMind key can take a few minutes to become valid, so retry
before assuming it's wrong.

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
