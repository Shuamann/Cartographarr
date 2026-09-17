# Changelog

Newest first. Each version is a heading with its date, then what was added,
changed and fixed. Settings, About reads this file, and compares it with the
copy on GitHub to say what an update brings.

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
