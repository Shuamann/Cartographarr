# Changelog

Newest first. Each version is a heading with its date, then what was added,
changed and fixed. Settings, About reads this file, and compares it with the
copy on GitHub to say what an update brings.

## 0.16.0 - 2026-09-23

### Added
- People who sign in as viewers can report a problem with what they watched, and see what they reported. Reporting
  from a play in History carries that play with it: the device, the time, whether it transcoded and whether it
  stalled, so nobody has to ask. Switch it off under Settings, Access
- An issue says what it was reported from, where it came from a play

### Changed
- Issues is no longer an admin's tab. A viewer sees their own reports and nothing else: not other people's, not who
  else watched the file, not where it sits on disk. Only an admin closes a report

## 0.15.0 - 2026-09-23

### Added
- `scripts/audit.py` checks both halves of the app against known vulnerabilities in one go

### Changed
- On a phone the filters fold behind one button, so the map gets the screen rather than three rows of controls, and
  the key opens as a sheet across the bottom
- The image the container is built from upgrades pip first, since pip is the one package in it that installs others

### Fixed
- The map's layer row pushed the page wider than a phone screen when a stream could not be placed

## 0.14.0 - 2026-09-23

### Added
- Library, Overview offers to forget stalls recorded before skipping and episode endings were told apart from
  buffering, since those cannot be sorted out now and drag every stall figure down

### Fixed
- Failed sign-ins are counted per caller behind a reverse proxy, reading the forwarded address past any proxy on the
  trusted list. Before this everyone behind one proxy shared a single count, so the limit protected nobody and could
  lock out a whole household

## 0.13.0 - 2026-09-23

### Added
- Raising an issue starts from what was watched: what is playing now and what was played lately, with posters and
  what each one is about. Search finds shows and films, and a show opens its episodes to pick one

### Fixed
- An episode's poster is taken from the show this app already knows about, instead of one Tautulli call per episode,
  so a grid of episodes fills in at once rather than crawling

## 0.12.0 - 2026-09-22

### Added
- A country can answer a VPN differently: stop streams from there, but only flag the ones arriving through a VPN or
  hosting address, or warn, or stop, or leave them alone entirely. Set it on the map or in the list under Rules

## 0.11.3 - 2026-09-22

### Fixed
- Map labels read in the language of whoever is looking, then English, rather than each country's own name:
  Greenland instead of Kalaallit Nunaat, Greece instead of Ελλάδα

## 0.11.2 - 2026-09-22

### Fixed
- Opening a report whose title has left the library took the Issues page down. It opens with nothing attached instead
- A report keeps the title it was given, rather than reading "Unknown title" once Plex no longer has the file
- The Raise an issue button wrapped into three lines; it is a "+ Report" button now

## 0.11.1 - 2026-09-22

### Fixed
- Reset sat on its own at the far edge of the filter bar; it now sits with the filters it clears
- Flag, warn and stop fill the width of the country panel, instead of leaving a gap beside Stop
- A country lights up as the pointer crosses it, so countries show they can be clicked even when none are listed yet

## 0.11.0 - 2026-09-22

### Added
- A key on the map, folded away until you want it: what the colours and sizes mean, and what a shaded country means

### Changed
- Countries are clickable straight away for an admin, with nothing to switch on first. The switch moved into the key
  for anyone who would rather not have them
- A click meant for a pin no longer opens the country picker as well

## 0.10.0 - 2026-09-22

### Added
- Countries are picked on the map. Turn on the Countries layer, click a country, and choose flag, warn or stop. The
  list shades the map: cyan for flag, amber for warn, red for stop. Boundaries ship with the app, so nothing is
  fetched from anyone while you use it

## 0.9.0 - 2026-09-22

### Added
- Comments and resolutions on an issue that came from Seerr go back to Seerr, signed with the name of whoever acted,
  because its API key would otherwise make everything read as the admin
- A replacement landing closes what was reported about that file, with a note saying what replaced it

### Changed
- An issue from Seerr can be commented on and resolved here. A Seerr that is down or turned off is reported as a note
  on the page rather than losing the decision, which stands here either way

## 0.8.0 - 2026-09-22

### Added
- Storage, under Library: which mount each file sits on, read from the paths Plex reports, with size, average bitrate,
  plays, transcodes and stalls per 100 plays for each. Give two mounts the same name and they count as one store, so
  several shares off one box read together. The file card says where a file lives

### Changed
- Tests no longer read the .env file sitting next to the code, so a developer's real addresses and keys stay out of
  the suite. It also stopped every test waiting three seconds on a LAN Tautulli it could not reach: 235 tests now run
  in 2 minutes 18 rather than 9 minutes 48

## 0.7.0 - 2026-09-21

### Added
- Home page, where everyone now lands: what is playing, anything open, and where to go next. Links for the services
  you have set up appear without being added, and each one can be renamed, given to admins or viewers only, moved or
  hidden under Settings, Home page, where links of your own go too

## 0.6.0 - 2026-09-21

### Added
- Blocked countries: a list beside the ban list, each country set to flag, warn or stop, added from Rules or from a
  place on the map, with what it would have caught before you let it act
- Issues can be raised, commented on and resolved here, so the ticket system works whether or not Seerr is set up

### Fixed
- A live stream from an address never seen before sat off the map for its whole run. Those addresses are looked up
  while the stream is playing, and the map now separates "on your network" from "waiting for a location"
- Viewers were told to add a MaxMind key on an empty map, which is an admin's job, not theirs

## 0.5.0 - 2026-09-17

### Added
- Issues tab: problems people reported in Seerr, each shown with the file, its findings, the plays behind it, whether
  those transcoded and whether they stalled during them, plus any earlier reports on the same file
- Now playing cards show time watched of total, and where the stream was when the app first saw it, marked on the bar

### Changed
- Now playing cards are wide enough to keep the bitrate on one line

## 0.4.0 - 2026-09-17

### Added
- Plays and sessions are both counted. A play paused and resumed, or carried to another device, is one play made of
  several sessions, and History, the dashboard, profiles, reports and the metrics show both
- Now playing cards say playing or paused, direct or transcode, the quality and the bitrate

### Fixed
- Progress bars never filled: the bar on every Now playing card, stream and log entry sat empty whatever the position

## 0.3.0 - 2026-09-17

### Added
- About page in Settings: this version, its changelog, and whether an update is out on GitHub
- The whole library is listed in about a minute, watched or not, and audio and subtitle tracks are read about 3,000 files a minute
- Tasks page in Settings: every background job, how often it runs, its last and next run, and any errors
- Replacements: a pop-up release picker with custom format scores and sorting, a History tab, and progress read straight from Sonarr and Radarr
- Replace a problem file through Radarr or Sonarr, then confirm or deny before it is imported
- Sign in with Plex, with new viewers anonymised by default
- Per-account viewer privacy
- Upload capacity read from Plex
- Explanations for problem files, with what to do about each
- Server health on the dashboard, and how each person and device plays
- Ban dialog with a reason and a length, from anywhere a device appears

### Changed
- Rule actions are gentler, and credential URLs are masked but editable without retyping
- Phone layout: tabs on their own row, segmented controls never squeezed
- Faint text is readable in both themes
- MapLibre upgraded to 6.10 for a security advisory

### Fixed
- History keeps one row per session instead of merging a paused and resumed play. A play carried from a phone to a TV
  now keeps both devices and addresses, and no longer appears twice, once without its episode number
- The app freezing on Requested, never watched
- Seeks and episode endings counted as stalls
- Files that never reached the download queue stuck at Queued
- Access gaps found by checking every route; changes requested by other websites are refused
- Repeated failed sign-ins are locked out, and security headers are sent

## 0.2.0 - 2026-09-16

### Added
- People tab: users and devices in one place, with full profiles
- History, Users and Devices tables, with expandable rows
- Live streams on the map, with a flyout that can act
- Shared account signals, and a managed ban list shown on the map
- Rule builder with nested, timed and windowed conditions
- Plex sharing: cut libraries down, or stop sharing
- Radarr, Sonarr and Seerr links, and who asked for a title
- Reports tab, Library tab and access review
- Every stream, upload use and the likely cause of each stall recorded
- Log tab with an audit of every change
- Heatmap, time scrubber, and accuracy circles on the map
- Branding, settings as sidebar pages, viewer privacy, Prometheus metrics

### Fixed
- The blank map after splitting the bundle
- API keys appearing in error messages and logs

## 0.1.0 - 2026-09-15

### Added
- Tautulli sync, IP geolocation and the map, with filters and a list view
- First-run setup, so no credentials are needed in the container
- Live activity, capabilities and enforceable rules
- Sign-in, roles and a settings page
