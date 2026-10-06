# Backlog

Everything known about and not done: the half-finished, the suggested, the
maybe. Enough of the thinking is written down that picking one up later does
not mean working it out again. Nothing here is a commitment and nothing here
is in order.

Keep this free of anything from a real install: no addresses, no account
names, no counts off somebody's server. The reasoning is the useful part and
it survives without them.

---

## Known gaps in what has already shipped

### The library source setting does nothing yet

Settings offers "The library from: Tautulli or Plex, directly". Nothing reads
it. The live activity switch beside it is wired and works; this one is a
control with no wire behind it, which is worse than not offering it.

Either finish the Plex library scanner or hide the control until it exists.
Plex gives the file path, size, container, codecs, bitrate, duration, the real
pixel dimensions and the IMDb, TMDB and TVDB ids in one pass at about half a
millisecond an item, which is more than Tautulli reports and one hop fewer, so
it is worth finishing rather than removing.

### Banning rides on "Run rules"

Turning off Run rules in Settings stops the sweep, and the ban list is
enforced by the sweep, so bans stop too. The ban list looks like its own thing
in the interface and reads like its own thing in the README. It defaults to on
so it is unlikely to be biting anybody, but somebody who turns rules off to
stop a noisy rule will quietly lose their bans as well.

Either enforce bans independently of that switch, or say plainly on the switch
what else it turns off.

### Tables that grow forever

`stream_sessions`, `stream_events`, `audit_log` and `enforcement_log` have no
pruning. `bandwidth_samples` is kept for a year and `task_runs` is capped per
task, so the pattern exists and these were simply never given it. Not urgent
at any volume seen so far, which is why it has not been done, but it is the
kind of thing noticed two years late.

### A dead function

`library.forget_rows()` has no caller. Either call it where the row cache
should be dropped, or remove it.

---

## Trusted devices, and quieter shared account signals

**What.** Mark a device as trusted, and untrust it again, from the device on
the Endpoints screen: a green tick beside the ban control that goes grey when
it is not trusted.

**Why.** The shared account signal fires when one account plays from two
places too far apart to be the same person. That is the right rule and it
catches real sharing, but it also catches the ordinary life of a household: a
phone on a mobile network, a laptop carried to work, a VPN whose exit moves
between cities. Those are the same person, every time, and the signal has no
way to know it.

**The rule to apply.** Where both ends of a pair are trusted devices of that
account, do not raise the signal. Two sides, not one: a trusted device paired
with an unknown one is exactly the case worth seeing, because a device
somebody recognises playing alongside one they do not is what sharing looks
like.

**What counts as trusted.** The intent is to trust the devices that clearly
belong to an account, which the data already shows: a device with a long
history on one account and no history on any other is not ambiguous. Worth
offering an automatic suggestion from that, with the tick as the final word,
rather than asking somebody to tick two hundred devices by hand.

**Open questions.**

- Trusting an account, or an address, as well as a device. An address is the
  more tempting of the two, because a home address is stable and trusting it
  would quiet a whole household at once, but it is also the thing a shared
  password looks like from the outside. Probably device first, and see.
- Whether trust should decay. A device not seen for a year is not obviously
  still theirs.
- Whether a trusted device should be exempt from anything else. Nothing else
  suggests itself yet, which is an argument for keeping the flag simple and
  letting a use case prove itself before the meaning is widened.

**Where it touches.** The device model needs a flag and a note of who set it
and when. The travel and concurrent checks need the pair test. Endpoints needs
the control. The existing ignore patterns already answer a nearby question, so
the two should be looked at together rather than built past each other.

---

## Settings descriptions behind an information icon

Every section carries a paragraph explaining itself. They are worth having and
they are worth reading once, after which they are the bulk of the page and the
controls are what somebody came for.

Collapse each one behind an information icon beside the section's name, which
expands it. Applies to every page, not a few. Worth remembering the expanded
state per section, so somebody reading a page carefully is not re-opening the
same note each visit.

---

## Finishing the move to Plex

Live activity reads from Plex directly and carries everything recorded about a
stream, including the viewer's address. Plex's own history does not: no
address, no transcode decision, no duration watched, which is why Tautulli
remains the only source for plays from before the switch.

### The library scanner

See the known gap above. The data is richer and the path is shorter; it simply
has not been written.

### Importing Tautulli's history

A one-time backfill of finished plays, so Tautulli can be switched off without
losing what it recorded before this app was watching.

The care needed is play identity. A paused and resumed play is one play, and
the import has to agree with how plays are already counted here or every
figure in the app moves. Reference ids exist for exactly this and the import
should use them rather than inventing a rule.

### Users and libraries from Plex

Still read through Tautulli. Plex knows both. Lower value than the two above
because the slow sync runs rarely and nothing is waiting on it.

---

## Issues as the system of record

Issues raised here are already kept here. The gap is importing what Seerr
holds, so that turning Seerr off loses nothing.

Worth doing because a report is more useful here than there: this app can put
it next to the file, the plays behind it, what went wrong during them and
whether the file is still on the disk, which is the whole question behind most
reports.

Requests are a separate thing and stay with Seerr for now. Replacing those
means becoming the thing that talks to Radarr and Sonarr about wanting
something that does not exist yet, which is a larger job than reading a list.

---

## The house style, applied everywhere

A row about a title now carries its artwork, a poster, the facts as label and
value and one clear action. Issues uses it. The library lists and the stream
cards have had a pass. Not yet done the same way: the Map's lists, the
Dashboard's lower half, Endpoints, Reports, Rules and Settings.

Settings also has a heading reading "People" above Add account, which is about
app accounts rather than the Endpoints tab. "Accounts" would be clearer now
that the tab has been renamed.

---

## Smaller things noticed and not done

- **The Map at phone width.** A few filter inputs are still under the size
  worth aiming a thumb at. The rest of the app was fixed; the map's own
  controls and the third party ones it embeds were left.
- **A weekly digest exists and is off by default.** Worth revisiting whether
  anything else belongs in it once it has been run for a few weeks.

---

## Looked at, measured, and not worth building

Recorded so that nobody has the idea again and spends a night proving the same
thing. Both of these sound good; the data does not support either.

### Abandoned plays as a quality signal

The idea is that people stopping halfway through means something is wrong with
the file. There is plenty of it to look at: on the install this was measured
on, about a quarter of all plays ended between a tenth and most of the way
through.

It tracks nothing the app could act on. Transcoded against direct play, and
local against remote, each moved the rate by two or three points, which is
noise at that sample size. The one strong split was films against episodes,
roughly double, and that is not a fault in the files: it is people watching a
film over two sittings.

### Films abandoned more often than normal

The obvious refinement: ignore the baseline, find the individual files
abandoned far more often than chance explains. Of the films with enough plays
to test at all, exactly one came out significant.

One file is not a feature. It is worth looking at that one by hand.

### Lazy loading the remaining routes

Measured, and the page weight did not justify the split. Recorded so it is not
measured again.

---

## Waiting on something outside the code

- **The first real tidy.** Tidying rewrites a whole file and has never been
  run end to end against a real one. Wants a disposable file to prove it on.
- **Update checks.** They need a GitHub token to read a private repository,
  and have been failing for the life of the install without one.
- **Tdarr and Trakt.** Both need an instance or a client id before anything
  can be written against them.
