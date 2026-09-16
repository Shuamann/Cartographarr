# Cartographarr

See where your Plex server is actually being watched from, and do something
about it.

Cartographarr sits on top of Tautulli. It maps every play by location, tracks
every device that has ever streamed, spots accounts being used in two places at
once, and can stop a stream or block a specific device.

## Why it exists

Plex has no way to ban one device belonging to someone you share with. The
device list at `plex.tv` only shows devices signed into your own account, so a
friend's Firestick is invisible to you. Your only account-level options are to
unshare them entirely or cut down which libraries they see.

So Cartographarr blocks by behaviour instead. It watches live playback, matches
a rule, and ends the stream with a message. Rules key on the Plex device id
rather than the player name, because anyone can rename "Living Room TV".

## What it does

- **Map** every play, with the location's real uncertainty drawn around it
- **Live activity** on the same map, with details and actions on hover
- **Rules** that stop streams: by device, user, platform, IP range, transcode
  decision, resolution, concurrent stream count, or how long something has sat
  paused
- **Shared account detection**: one account playing in two cities at once, or
  moving faster than a plane between plays
- **Devices, users and history**, all searchable and filterable
- **Links out** to Plex, IMDb, TMDB and Trakt from any title

## Install

```bash
docker compose up -d --build
```

Open `http://your-server:6277`, create the admin account, and follow the setup
prompts. Nothing needs to be configured in advance and no keys go in your
container config unless you want them there.

You will need a Tautulli URL and API key. A free
[MaxMind GeoLite2](https://www.maxmind.com/en/geolite2/signup) account is
optional but there are no map pins without one.

The first sync pulls your whole history. On a large library expect a few
minutes, almost all of it fetching artwork and metadata once. After that a
cycle with nothing new takes about a tenth of a second.

### On Unraid

Data lives in `/mnt/user/appdata/cartographarr` and the container runs as
`99:100` to match. Using the Docker template instead of compose: map `/data` to
your appdata path and publish port 6277.

### Configuring by environment variable

Every setting can also come from the environment, which suits Unraid templates.
**An environment variable wins and shows as read-only in Settings.** Leave one
out and the UI owns it.

| Variable | Notes |
|---|---|
| `TAUTULLI_URL` | The address Cartographarr can always reach |
| `TAUTULLI_API_KEY` | Tautulli, Settings, Web Interface |
| `TAUTULLI_LOCAL_URL` | A LAN address, preferred when reachable |
| `MAXMIND_ACCOUNT_ID`, `MAXMIND_LICENSE_KEY` | For map locations |
| `AUTH_PROXY_ENABLED`, `TRUSTED_PROXY_IPS` | See below |

## Putting it behind a reverse proxy

Cartographarr has its own login, so it is safe to expose without one. If you
already run Authelia, Authentik or Cloudflare Access, turn on proxy sign-in in
Settings and list the addresses allowed to send the header.

The header is only trusted from those addresses. Local login stays available on
purpose, so a broken proxy config cannot lock you out.

## Blocking a device

1. Find it under **Devices**, or hover its stream on the map
2. Hit **Block**, which opens a rule with the device id filled in
3. Leave dry run on and watch the enforcement log
4. Turn dry run off when the log looks right

Rules ship in dry run. They record what they would have done and stop nothing
until you say so.

**Already using JBOPS `kill_stream.py`?** Turn those notification agents off
before enabling enforcement, or both will fire on the same stream.

## A note on locations

An IP address gives you a city, never an address. GeoLite2 reports its own
margin of error, which ranges from about 5 km to 1000 km, and the map draws
that margin rather than dropping a confident pin on a rooftop. A stream from a
VPN is placed where the VPN is, and gets labelled as such.

Treat a pin as a neighbourhood, not a house.

## Development

```bash
cd backend && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest -q
```

```bash
cd frontend && npm install && npm run dev
```

Vite proxies the API to the backend on 6277.
