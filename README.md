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
- **Reports** on plays, buffering, streams, server load and rule matches,
  grouped and split however you like, with charts, tables and CSV export
- **Library health**: files judged by how they are watched, what exactly is
  wrong with each and how to fix it, with a hand-off to Radarr or Sonarr
- **Access review**: who you share with, what they can see, and whether they
  still use it
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
| `ENFORCE_ENABLED`, `ENFORCE_DRY_RUN` | Whether rules run; `ENFORCE_DRY_RUN=true` locks every rule to record only |
| `UPLOAD_CAPACITY_MBPS` | Your upload, for stall causes and the upload alert |
| `API_DOCS` | `true` turns on /docs and /openapi.json, off by default |
| `ALLOW_FRAMING` | `true` lets dashboards such as Organizr show Cartographarr in a frame (also in Settings, Access) |

## Signing in with Plex

Switch on **Offer Sign in with Plex** in Settings, Access. A Plex account signs
in as the Cartographarr account linked to it under Accounts, or as a viewer
account with the same email. Usernames are never matched, and an admin must be
linked to their Plex account before Plex can sign them in. With **Let people
you share with sign in as viewers** on, anyone Tautulli lists as having access
gets a viewer account the first time. Cartographarr uses the Plex token once to
learn who signed in and does not keep it.

## Putting it behind a reverse proxy

Cartographarr has its own login, so it is safe to expose without one. If you
already run Authelia, Authentik or Cloudflare Access, turn on proxy sign-in in
Settings and list the addresses allowed to send the header.

The header is only trusted from those addresses. Local login stays available on
purpose, so a broken proxy config cannot lock you out.

## Banning a device

Hit **Ban device** on a stream, on the map, or on the device in **People**. It
asks for a reason, then adds the device to the ban list. **Unban** is in the
same places. On the Rules page the ban list can also ban a device found by
name, owner or id, for an hour, a day, a week, 30 days or for good. A timed ban
stops applying the moment it ends and leaves a Log entry. A ban's reason can be
changed later.

The ban list runs as a built-in rule ahead of all the others, with its own
record only switch, and shows up in the Log like any rule. The message a
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

Some conditions take a number of seconds, times or hours:

- **Buffering right now for** N seconds, **times buffered** and **time spent
  buffering** on this stream, and **stream running for** N seconds. Timed from
  the activity checks, so accurate to a few seconds, and started again if the
  app restarts.
- **N in the last H hours**: plays by this user, devices or addresses they
  used, cities they played from, and times this user or device buffered.
  Plays count once they finish and sync.

- **Times a rule caught this user (or device) before**, counting other streams
  only. Put a stopping rule using it above a warning rule, and the first time
  someone breaks a rule they are warned; the next time they are stopped.
- **Country, city or network new for this user**, once they have five plays
  of history.

Besides stopping a stream, a rule can record it, notify you through Apprise,
post to a webhook, or **message the viewer**: set a viewer message address in
Settings, an Apprise URL with `{email}` filled in from their Plex account, for
example `mailtos://you:app-password@gmail.com?to={email}`.

A rule that only records or notifies does so once per stream, not again every
check while it stays true.

Each rule, and the ban list, has its own **Record only** switch. A new rule
starts in record only: it logs what it would have done and stops nothing.
Watch the Log for a while, then let it act. Setting `ENFORCE_DRY_RUN=true`
locks every rule to record only.

### Coming from JBOPS kill_stream.py

If you block devices today with Tautulli notification agents running
`kill_stream.py`, both will act on the same stream once rules are live. To move
over:

1. Ban each device in Cartographarr, or rebuild the rule, in record only
2. Check the Log shows them being caught
3. Turn off the Tautulli notification agents
4. Switch the ban list or rule to act

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

## Reports

Pick what to report on, a measure, what to group by and optionally what to
split each row by, then narrow it with the same filters as the map and
History. Rows link to the user, device, address or title they name.

- **Plays**: plays, watch time, completion, transcodes, and how many different
  users, devices, addresses and titles
- **Buffering**: how often and how long streams stalled, by device, network,
  resolution, direct play or transcode, and so on. Recorded from live activity
  from the day this version is installed, so it starts empty.
- **Rule matches**: what each rule caught and what happened

A few starting points are built in, such as buffering by device and when
people watch. Admins can save their own. Buffering and rule matches are for
admins only; with viewer privacy on, a viewer's report on people or titles
covers only their own plays.

## Streams, upload and stalls

While it runs, Cartographarr records every stream it sees: the worst decision
during the stream (one that switches to a transcode when subtitles go on
counts as a transcode), every reason it transcoded, hardware transcoding, peak
bandwidth and stalls. It also keeps the busiest moment of each minute of
upload. Both start empty and grow from the day this version is installed.

Every stall gets a likely cause, worked out again as patterns form:

- **Upload nearly full**, if you set your upload capacity in Settings
- **Server side**: someone else stalled at the same moment
- **The file**: other people stall on the same title
- **The viewer**: they stall on many titles while nobody else does

Set **Upload capacity** in Settings and Cartographarr also notifies you
(through Apprise, at most every half hour) when remote streams nearly fill it.

## Library health

The **Library** tab (admins only) judges files by how they are actually
watched. File details are read from Tautulli, 150 titles each sync until the
whole library is covered.

- **Problem files**: over a bitrate limit and watched remotely, stalling, or
  transcoded for most remote viewers
- **Why streams transcode**: each reason, on which platforms, the worst
  titles, and the usual fix
- **Messy files**: no audio most devices can play, image or styled
  subtitles, piles of duplicate subtitles, untagged audio, old containers
- **4K copies**: whether a 4K picture ever reaches a screen
- **Requested, never watched**: Seerr requests the requester never played

Open any file for what exactly is wrong with it, named from its own tracks and
how it played, and how to fix it. For plays from before streams were recorded,
the reason is read back from Tautulli. **Search for a replacement** asks
Radarr or Sonarr to look for a better release (it only grabs one your quality
profile rates higher), and **Tag for replacement** tags the title
`cartographarr-replace` to pick one by hand. Nothing is deleted.

## Access review

The **Sharing** tab has two views. **Who has access** comes from Plex and can
change which libraries someone sees or stop sharing. **Access review** comes
from Tautulli and history, so it works without a Plex token: everyone, the
libraries shared with them, plays, when they last watched, their devices and
any banned ones, with people who have not watched in 90 days first.

## Monitoring

Uptime Kuma: give Settings a push monitor URL and every sync pings it, so
the monitor watches the sync, not just the container.

Prometheus and dashboard tiles: set a metrics token in Settings. That
switches on:

- `/metrics`, Prometheus text format
- `/api/summary`, one JSON object for Homepage's custom API widget or Homarr

Send the token as `Authorization: Bearer <token>` or `?token=<token>`. Both
return counts only: streams, transcodes, plays, users, devices, unreviewed
devices, open signals, bans, rules and the last sync time. Nothing that
names a person, an address or a title.

A Homepage tile:

```yaml
- Cartographarr:
    href: https://cartographarr.example.com
    widget:
      type: customapi
      url: http://cartographarr:6277/api/summary?token=YOUR_TOKEN
      mappings:
        - field: streams
          label: Streams
        - field: devices_unreviewed
          label: New devices
        - field: signals_open
          label: Signals
```

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
