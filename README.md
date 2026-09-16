# Cartographarr

See where your Plex server is actually being watched from, and do something
about it.

Cartographarr sits on top of Tautulli. It maps every play by location, tracks
every device that has ever streamed, spots accounts being used in two places at
once, and can stop a stream or ban a specific device.

## Why it exists

Plex has no way to ban one device belonging to someone you share with. The
device list at `plex.tv` only shows devices signed into your own account, so a
friend's Firestick is invisible to you. Your only account-level options are to
unshare them entirely or cut down which libraries they see.

So Cartographarr blocks by behaviour instead. It watches live playback, matches
a rule, and ends the stream with a message. Rules key on the Plex device id
rather than the player name, because anyone can rename "Living Room TV".

## What it does

- **Map** every play, with the location's real uncertainty drawn around it.
  VPN locations are purple, banned devices red, live streams amber. A heat map
  can count plays, devices or users.
- **Live activity** on the dashboard and the map, with the same card in both:
  what is playing, how, from where, and buttons to stop it or ban the device
- **People**: every user and their devices in one list. Open anyone for where
  they watch from, what they watch, their devices, their history and what has
  happened to them. Open a device to see every account that has used it.
- **Ban list**: one list of devices that may not stream
- **Rules** built from dropdowns, with all/any groups inside each other, for
  anything the ban list does not cover: no remote 4K, no transcodes at night,
  no VPNs, a cap on streams per account
- **Shared account signals**: one account playing in two places at once, or
  moving faster than a plane between plays
- **Log** of every stream stopped and every change made in the app
- **Links out** to Plex, IMDb, TMDB and Trakt from any title, plus Radarr,
  Sonarr and Seerr if you connect them

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

Building from a clone, and updating later with the same line:

```bash
cd ~/Cartographarr && git pull && docker build -t cartographarr:latest . && docker rm -f cartographarr && docker run -d --name cartographarr --restart unless-stopped -u 99:100 -p 6277:6277 -v /mnt/user/appdata/cartographarr:/data -e DATA_DIR=/data -e TZ=Etc/UTC cartographarr:latest
```

Set `TZ` to your own time zone. Rules that use a time of day go by it.

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
| `ENFORCE_ENABLED`, `ENFORCE_DRY_RUN` | Whether rules run, and whether they only record |

## Putting it behind a reverse proxy

Cartographarr has its own login, so it is safe to expose without one. If you
already run Authelia, Authentik or Cloudflare Access, turn on proxy sign-in in
Settings and list the addresses allowed to send the header.

The header is only trusted from those addresses. Local login stays available on
purpose, so a broken proxy config cannot lock you out.

## Banning a device

Hit **Ban device** on a stream, on the map, or on the device in **People**. It
asks for a reason, then adds the device to the ban list. **Unban** is in the
same places.

The ban list runs as a built-in rule ahead of all the others, so it follows
the same dry run setting and shows up in the Log like any rule. The message a
banned device sees is in Settings.

If you banned devices before the ban list existed, each one became its own
rule. The Rules page spots those and offers to move them in.

## Rules

Build a rule from dropdowns: pick a condition, how to compare it, and a value.
Put conditions in groups that need all or any of them to be true, and groups
inside groups. **Check against live streams** shows what a rule would catch
right now without stopping anything.

Conditions that need something you have not set up, like a MaxMind key for
country or Seerr for who requested a title, are greyed out with what they need.

Rules ship in **dry run**. They record what they would have done and stop
nothing. Watch the Log for a while, then turn dry run off in Settings.

### Coming from JBOPS kill_stream.py

If you block devices today with Tautulli notification agents running
`kill_stream.py`, both will act on the same stream once rules are live. To move
over:

1. Ban each device in Cartographarr, or rebuild the rule, while dry run is on
2. Check the Log shows them being caught
3. Turn off the Tautulli notification agents
4. Turn off dry run

## Shared account signals

A signal means one account played in two places too far apart. **At once** is
two plays overlapping in time. **Too fast** is a gap between plays that is far
too short for the distance.

Open a signal to see both plays side by side: what was watched, when, on which
device, from where and on which network, with the distance and the time between.

- **Reviewed** closes that one signal.
- **Ignore this pattern** says this is normal for this person, like a second
  home or a VPN they always use. It closes matching signals already found and
  records new ones as ignored. Ignored patterns are listed on the dashboard and
  can be undone.

A play left paused keeps its session open for hours or days. Signals measure
from when a play was last watched, not when the session closed, so pausing on
a phone and later watching on the TV does not count.

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
