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
  can count plays, devices or users, and a **Globe** toggle wraps the map round
  a planet instead of flattening it.
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
cd ~/Cartographarr && git pull && docker build --build-arg GIT_COMMIT=$(git rev-parse HEAD) -t cartographarr:latest . && docker rm -f cartographarr && docker run -d --name cartographarr --restart unless-stopped -u 99:100 -p 6277:6277 -v /mnt/user/appdata/cartographarr:/data -e DATA_DIR=/data -e TZ=Etc/UTC cartographarr:latest
```

Set `TZ` to your own time zone. Rules that use a time of day go by it.

To tidy a file's tracks, the container also needs to read the media, at the
paths Plex reports. Add one `-v` per share, with the same name inside:

```bash
-v /mnt/user/movies:/movies -v /mnt/user/tv:/tv -v /mnt/user/kidsmovies:/kidsmovies
```

**Settings, Behaviour, Tidying files** says whether this worked: it checks a
sample of the paths Plex reports against what the container can actually open,
and names the shares that are missing. Where the names cannot match, map them
there instead. Everything else in the app works without these mounts.

`GIT_COMMIT` tells the app which commit it was built from, so Settings, About
can say how many commits behind it is. Leave it out and it compares version
numbers instead.

### Updates

Settings, About shows the installed version, the changelog, and whether GitHub
has something newer; Settings is flagged in the top bar when it does. It checks
twice a day and sends nothing about your server. Turn it off there, point it at
a fork, or, while the repository is private, give it a GitHub token that can
read it. Every release adds a section to [CHANGELOG.md](CHANGELOG.md).

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

Some things look like two places and are not, and none of them are flagged:

- **One device on two networks.** A phone that leaves mobile data for the wifi
  at home is recorded against two addresses. One device cannot be in two
  places, so a changed address is a changed network.
- **One viewing carried to another device.** The phone on the way home and the
  television once there is the same thing continuing, so long as the second
  play begins within half an hour of the first leaving off. Two people watching
  the same title from two cities overlap for the length of it, not for a few
  minutes, and are still flagged.
- **A play left paused**, which keeps its session open for hours or days.
  Signals measure from when a play was last watched, not when the session
  closed, so pausing on a phone and later watching on the TV does not count.

A signal also names any network that has been putting that account in several
cities anyway, with which ones, read from their own plays over the last six
months. That is what a mobile connection looks like, and it explains a signal
on its own.

Each signal also says how often that account has been flagged between those
same two places. A route that keeps coming back is usually how that connection
is carried, a mobile network or a VPN with a favourite exit, rather than two
people.

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
- **One stream that kept stalling**: the same sitting stalled three times or
  more, which is a stream that was not being kept going rather than bad luck
- **The viewer**: they stall on many titles while nobody else does

Set **Upload capacity** in Settings and Cartographarr also notifies you
(through Apprise, at most every half hour) when remote streams nearly fill it.

## Library health

The **Library** tab (admins only) judges files by how they are actually
watched. Every movie and episode is listed from Tautulli, watched or not, in
about a minute after startup and again every 6 hours: bitrate, resolution,
codecs and size. Audio and subtitle tracks are then read about 3,000 files a
minute until done. Files removed from Plex drop out at the next scan, and a
file that changed size (an upgrade or a replacement) has its tracks read again.
Both jobs show on the Tasks page in Settings.

- **Files worth attention**, the same rows asked three ways:
  - **Trouble for viewers**: stalling, transcoded for most remote viewers, or
    a bitrate too high for the way it is watched
  - **Awkward to play**: no audio most devices can play, image or styled
    subtitles, piles of duplicate subtitles, untagged audio, old containers,
    and anything that had to be converted for the people who actually watched
    it, which catches the files whose track list looks perfectly ordinary
  - **Taking up room**: big, and either never played, not played in years, or
    4K nobody has ever been sent in 4K
- **Why streams transcode**: each reason, on which platforms and which
  devices, the worst titles, and the usual fix
- **4K copies**: whether a 4K picture ever reaches a screen
- **Requested, never watched**: Seerr requests the requester never played

Anything you decide to live with can be kept, with a reason, and stops being
suggested in all three.

Open any file for what exactly is wrong with it, named from its own tracks and
how it played, and how to fix it. For plays from before streams were recorded,
the reason is read back from Tautulli.

**Find a replacement** has Radarr or Sonarr search the indexers and shows each
release as a tile against the current file: what it would fix, what it is made
of, size, rough bitrate, seeders, age, indexer and the profile score. Filter by
resolution, source, size, or whether the service would import it by itself.
Best first means most of this file's problems solved, then the service's own
score, rather than one blended number that would have to decide what a fixed
soundtrack is worth in custom format points. Download one and it is
followed until ready. Radarr and Sonarr import an upgrade by themselves;
anything else, which is most compatibility swaps, waits under **Replacements**
beside the current file to **Confirm** (import it in place of the old file) or
**Deny** (delete the download and block that release). **Tag for replacement**
tags the title `cartographarr-replace` instead, to pick one by hand.

### The problem bitrate

**Library** calls a file a problem for remote viewers when its bitrate is above
**library_bitrate_threshold_mbps**, which starts as a round 20. Once enough
remote streams have been recorded, Settings offers a number read from this
server instead: the bitrate nine in ten clean remote streams stayed under, next
to what the ones that stalled were running at. It fills the field and leaves
the saving to you, because a stall can be a bad evening on somebody else's line
as easily as a file that is too big. It stays quiet when the streams do not
support an answer.

## Making it yours

**Settings, Appearance** takes a name, a logo, and two sets of colours.

The **accent** is the one colour buttons, links, map pins and charts are built
from. The hover colour, the ink on top of a button and the wash behind a
selection are worked out from it, in light and in dark, so it only has to look
right once, and it reaches the borders and raised surfaces too rather than
being a highlight on whatever is selected.

The **theme editor** underneath sets the page, the panels and menus, the top
bar and the text, per theme. Everything else (raised panels, borders, quieter
text) is worked out from those four, a step at a time, so they cannot
disagree. A few dark schemes are offered to start from, for anyone who wants
the blue-grey gone. Both are read before anyone signs in, so the sign-in page
is the app's face too.

## The home page

Behind it, a globe turns: the same basemap as the Map tab, in your colours,
carrying the same layers on small toggles, so where people watch from is the
first thing the app says. It stops when the tab is hidden or the machine asks
for less motion, and is left out where there is no WebGL.

Everyone lands on **Home**: how many streams are playing, anything reported and
still open, and where to go next. A link appears for each service that is set
up, without anyone adding it: Plex for everyone, the request service when it is
configured, and Sonarr, Radarr and Tautulli for admins.

Under **Settings, Home page** each link can be renamed, pointed somewhere else,
given to admins or viewers only, moved or hidden, and links of your own added
beside them.

## Blocked countries

Click a country on the map: flag, warn or stop, and it shades in. **Key**, at
the bottom of the map, says what every colour and size means, and is where the
country layer can be switched off. Cyan is flag, amber is warn, red is stop. Boundaries
are part of the app (Natural Earth, public domain), so nothing is fetched from
anyone else while you use the map, and they load only when the layer is on.

Each country can answer a VPN differently. An address in a country says where
somebody is; a VPN or hosting address there says where their provider is, which
is a weaker claim. So a country set to **stop** can be set to **flag only**
over a VPN, or to warn, stop, or leave those streams alone entirely. Set it in
the panel on the map, or in the list.

The same list sits beside the ban list in **Rules**. Each one says what
should happen when a stream comes from there: **flag** records it in the Log,
**warn** messages the viewer, **stop** ends the stream. Add a country from that
list, or from a place on the map. Like the ban list it starts recording only,
and **What would this have caught?** counts the plays it would have matched
before you let it act. Turned around, the list becomes the only places allowed,
and everywhere else is flagged.

## Issues

The **Issues** tab (admins only) reads what people reported in Seerr, every
five minutes, and shows each report next to what this server knows: the file's
tracks, bitrate and findings, the plays behind it, whether those transcoded,
and whether they stalled while that person watched. Earlier reports on the same
file are listed with it, and Find a replacement is one click away in the file
card. Nothing is written back to Seerr yet.

Reports on an episode land on the episode's own file, not the show.

Raising one starts from what was watched: what is playing now, then what was
played lately, with posters and a line about each. Searching finds shows and
films, and picking a show opens its episodes.

A new report goes out through Apprise if notifications are set up, with what
this app already knows about that file attached. **Reports** can chart reported
problems by kind, by title, by who reported them, and open against resolved.

People who sign in as viewers can report what they watched, and see what they
reported. Reporting from a play in their History carries that play with it: the
device, the time, whether it transcoded and whether it stalled. They see their
own reports and nothing else, and only an admin closes one. Turn it off under
**Settings, Access**.

Comment on an issue, resolve it or reopen it from here. One that came from
Seerr is updated there as well, signed with the name of whoever acted, since
Seerr's API key would otherwise make every message read as the admin. If Seerr
is down or has been turned off, the decision still stands here and the page
says Seerr was not updated.

When a replacement for a file finishes importing, whatever was reported about
that file is closed with a note saying what replaced it.

## Browse

**Library, Browse** is the whole library as a wall of posters, sorted by
whatever is wrong today: biggest per hour, highest bitrate, most stalls, most
transcoded, most watched, least watched, or most wrong with it. Size per hour
is there because bitrate alone cannot be compared across a three hour film and
a forty minute cartoon.

Each poster carries what the app can prove about that file: it stalled for
somebody, it was transcoded for most remote viewers, its audio had to be
converted, nobody has played it. Press one and the whole file card opens, with
its findings, the replacement search and the track tidying.

Narrow by problem, size per hour, resolution, library, audio language, films
against episodes, or a title search. Switch to the list for ticks and bulk
tagging in Radarr or Sonarr, a hundred at a time; on the wall, hold ctrl or
shift while pressing to add to the same shortlist. Nothing is downloaded and
nothing is deleted by tagging.

## Tidying a file's tracks

Most of what the Library finds wrong with a file is not the picture: styled
subtitles a television burns in, a pile of duplicate subtitle tracks, audio no
common device can decode, a container from another decade. **Tidy the tracks**,
on a file card, fixes those with ffmpeg inside this container. Nothing is
re-encoded, so a film takes minutes and loses no quality.

What is offered comes from the file's own tracks:

- Styled (ASS) subtitles converted to SRT, which stops the burn-in
- Picture subtitles dropped where the same language exists as text, and kept
  where it does not, because a picture subtitle is better than none
- Duplicate subtitle tracks dropped, keeping the first of each kind
- An AC3 track added beside audio nothing can play, never instead of it
- An old container repackaged to mkv, streams copied across

The panel also lists the file's own tracks. Untick a subtitle or audio track
to drop it, and choose which audio track plays first; all, none and first
language only are there for files carrying fifty subtitle tracks. A choice
made here wins over anything worked out from Settings, since somebody is
looking at the real list. Unticking every audio track keeps them all: a file
is never left with no sound.

Three of the steps answer to Settings, because there is no sensible default:
an **audio language to put first** when a file has several, **subtitle
languages to keep**, and **audio languages to keep**. Languages are the three
letter codes the tracks carry (eng, spa, jpn). A file that would be left with
no sound keeps everything whatever the setting says.

Rules can do the same work: **Tidy the tracks** is a rule action, so "every
file with styled subtitles" or "anything reported for bad audio" can be
handled without pressing anything. It starts as record only like every rule,
and answers to the same daily cap.

To use it, mount the media in the container. The shares want to be where Plex
already reports them (`/movies`, `/tv`), in which case there is nothing to
configure; where they differ, set **media_path_map** in Settings as
`plex=here` pairs. The compose file has the mounts commented out ready.

One file is worked on at a time, with progress and a Stop button at the top of
**Files worth attention**. The result is checked against the original, for
length and for still having a picture in it, before it replaces anything.

## Taking up room

**Files worth attention, Taking up room** lists big files nobody watches,
biggest first, with why each one stands out: never played, not played in years,
or 4K that has only ever been sent to a screen scaled down. Each says which
storage it is on.

Nothing is deleted from here. Plex, Radarr and Sonarr own the files, so this
says what is worth deciding about and hands over. A file you decide to keep is
marked kept, with a reason, and stops being suggested until you put it back.

## Storage

A Plex library can span more than one place: an array share and a network SSD,
say. **Library, Storage** reads the mount each file sits on from the path Plex
reports, and shows what each one holds and how watching from it goes: size,
average bitrate, plays, how many transcoded, and stalls per 100 plays. When one
store stalls far more than the rest, it says so.

Give two mounts the same name and they count as one store, which is how several
shares off one box read together. Where several libraries share a mount
(`/mnt/user/movies`, `/mnt/user/tv`), raise **library_store_depth** so the name
goes deeper than the first part of the path.

**Why**, beside a store, breaks its stalling down: who it happened to, on what
device, which titles, and whether it was on your own network or out on the
internet. A bad number is not proof of bad storage. Stalls on your own network
are where storage trouble shows up; stalls from viewers outside the house are
usually the line out of the house or the bitrate of the files.

Underneath, each store carries its last twelve weeks, as the share of plays
that stalled at all. That is what tells a disk going downhill from one bad
evening. Weeks from before this app started watching live streams are left as a
gap rather than drawn as weeks where nothing went wrong.

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

Before a release, or whenever a dependency moves:

```bash
cd backend && .venv/Scripts/python scripts/audit.py
```

It asks pip-audit about the Python packages and npm about the JavaScript ones,
and says nothing about this server to either.
