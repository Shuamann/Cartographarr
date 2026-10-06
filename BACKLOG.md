# Backlog

Everything known about and not done: the half-finished, the suggested, the
maybe. Enough of the thinking is written down that picking one up later does
not mean working it out again. Nothing here is a commitment and nothing here
is in order.

Keep this free of anything from a real install: no addresses, no account
names, no counts off somebody's server. The reasoning is the useful part and
it survives without them.

---

## How this app is built, and why

Read this part first. The list below makes sense only against it, and most of
it was arrived at by measuring rather than by deciding, so the numbers are
kept: they are the argument.

### Where the data comes from

Three services, with a clear division of labour.

**Plex** is the source of truth for anything happening now. A live session from
Plex carries the viewer's address, whether they are local, relayed and secure,
the device, the player and the account. That is everything recorded about a
stream, which is why nothing is lost by asking Plex rather than asking
something that asks Plex. It answers in about nine milliseconds. The library
listing gives the file path, size, container, codecs, bitrate, duration, the
real pixel dimensions and the external ids, at roughly half a millisecond an
item.

**Tautulli** is a recorder. It watches Plex and writes down what it sees, and
that is why it holds something Plex does not: an address against a play from
years ago. Plex's own history was checked against a real server and carries no
address, no transcode decision and no duration watched. So Tautulli is the only
possible source for plays from before this app was watching, which makes it an
import rather than a dependency. Everything else it does, Plex can do directly.

**Seerr** is the only source of requests, because neither Plex nor the arrs
have a concept of somebody asking for something that does not exist yet. Issues
are different: they are already kept here, and Seerr is only a place to import
from.

One fact that makes the whole switch possible and was verified rather than
assumed: the account id Plex reports in a session is the same number this app
already files everything under. Every ban, every privacy scope and the whole of
history key on it. Had those been different id spaces, changing the source
would have silently broken every per person feature.

### Both sources answer in the same shape

An adapter turns a Plex session into the field names Tautulli returns, exactly,
so the tracker, the rules, the ban list, the map and the stream cards do not
know or care which source answered. A test compares the adapter's keys against
the list the rest of the app reads, because a field quietly missing would be a
blank on a card rather than an error.

The subtle part is the one word a session is judged by. Plex answers the
transcode question per stream; this app wants one answer for the session. A
real stream had its video copied and its audio converted, which Tautulli calls
a transcode and which reading the video decision alone calls a copy. Every rule
anybody writes matches on that word. Taking the wrong one would have stopped
those rules firing with no error anywhere. It takes Tautulli's meaning, and
there is a test named after the stream that caught it.

### What a ban is, and what it is not

A ban is an explicit act: somebody opened a dialog, named one device or one
address, typed a reason and chose how long. A rule is a standing pattern that
may well be written speculatively. They are not the same kind of thing and
should not share a default. Rules start recording only; the ban list acts
unless told otherwise.

Two faults once made bans silently do nothing, and both are worth remembering
because they are the same shape. The ban list's switch was unset and unset fell
through to an old global dry run flag that starts on. And the address ban rule
is handed a negative id so its cooldown stays stable between sweeps, while the
code decided which settings a rule answered to by testing only whether that id
was negative, which the country rules are too. The lesson in both: a safety
default that cannot be distinguished from a broken feature is a broken feature.

Built in stops are also deliberately exempt from the logging cooldown. The
cooldown exists so a stubborn client cannot fill the log, which is right for a
rule that fires now and then and wrong for a ban: a stop that does not land
should be tried again on the next poll, not a minute later.

### Honesty about what is known

A recurring decision, applied in several places, and worth keeping.

Where the app cannot answer something, it says so rather than giving a figure
it cannot support. Library space has no history before the daily note began, so
a library with nothing written down reads as "no history yet" and not as
"unchanged": those are different answers and the second gets believed. A file
this container cannot reach is said differently from a file that is gone,
because one is a mount to fix and the other is a file to replace. Detail that
only Plex reports is left empty on a stream recorded through Tautulli rather
than guessed. Not told and no are different answers.

The same principle decides what is not built. Space gained or lost could not be
reported until the scan began writing down what each library held, because
nothing records when a file arrived and the figure would have been invented.

### How the interface is meant to look

The reference is Seerr's issue list: artwork that bleeds across a row behind a
scrim, a poster, the year above the title, the facts as label and value pairs,
and one clear action. Not boxes of text. A row that carries its artwork says
what it is about before anybody reads a word, and the art is already on disk
because the poster is.

Rules that fell out of doing it:

- The scrim is opaque where the words are and nearly gone at the far edge, so
  text contrast never depends on which picture a row happened to get.
- Every control is one height. Six button styles at four different heights
  meant any row holding more than one of them stepped up and down the page,
  which is most of what "cluttered" turns out to mean when you go looking.
- One scale for text and one for space, in the token layer, so a page is not
  six sizes picked one at a time.
- A fact belongs on one line. Columns are sized to their contents and packed
  left rather than stretched, because a dozen short values spread across an
  ultrawide are harder to read than the same values in a block.
- When something must be truncated, the part that identifies it survives. A
  title clipped to "The Show - S01 - ..." has cut off the thing somebody is
  reading it for.
- The app asks its own questions. The browser's confirm, prompt and alert are
  gone and a test stops them coming back: they arrive in the wrong typeface,
  say "127.0.0.1 says" above the question, cannot show a warning in red, and
  carry a tickbox that silently answers no to everything afterwards.
- A confirmation is worth asking only when the answer could be no. Several were
  deleted rather than restyled, because a dialog that is only ever clicked
  through is training for clicking through the ones that matter.

### Traps that have already been paid for

Each of these cost real time. They are written down so they cost it once.

- **A query with an OR can pick the wrong index.** Finding a show's artwork
  through its episodes, asked as one statement with an OR and a media type
  test, made SQLite prefer the media type index and scan every episode in the
  library. Asked as two statements it uses the keys it was given. Thirty two
  milliseconds a poster became under a third of one. Adding the obvious index
  first changed the plan and not the time, which is why the fix is measured
  rather than reasoned.
- **A new HTTP client per request is a new TLS handshake.** Fetching artwork
  that way cost four times what the picture did. One client, held open, for
  anything fetched in bulk.
- **Discovery is expensive and the answer does not change.** Letting the Plex
  library find the server takes twenty seconds because it waits out addresses
  that are unreachable from outside the house. Connecting to a stored address
  takes a fifth of a second.
- **The tests reload the application modules.** A name bound at module level in
  a service points at the class from before the reload, and SQLAlchemy renders
  it as the same table joined to itself. Import models inside the function.
- **A button inside a button is neither valid nor well behaved.** Making the
  parts of a card clickable meant turning the card into something that behaves
  like a button rather than being one.
- **Measure before optimising, and after.** More than once the obvious cause
  was not the cause: the index that did not help, the test suite whose cost was
  the scheduler rather than the fixtures, the poster slowness that was the
  handshake. Every performance claim in the changelog has a number behind it
  because every one of them was checked.

### Working practice

- Nothing ships without the full test suite passing, a sweep of every page in a
  real browser, and a scan of the diff for anything personal.
- The version is bumped in four places and the changelog gets an entry, every
  time.
- Commits are made as Shua Theater, and the message explains the reasoning
  rather than listing the files.
- No em dashes anywhere. A test enforces it.
- Nothing from a real install is ever committed: no addresses, no account
  names, no tokens, no counts off somebody's server. A suggestions document
  full of them was once pushed and had to be removed from history. The
  reasoning survives without them, which is why this file reads as it does.
- Guards are cheap and worth adding when a mistake is made twice: the em dash
  test, the duplicate class name test, the browser dialog test and the tab
  label test all exist because something slipped through once.

---

## Known gaps in what has already shipped

### The scan walks shows one at a time

The Plex scan walks shows one at a time, a request each, in one worker
thread. At about ten milliseconds a request that is fine for a scan every six
hours, so it was left simple. If a very large TV library makes it slow, list
episodes a section at a time instead, which is one paged listing rather than a
request per show, after checking against a real server that the listing
carries the show and season keys.

### Tables that grow forever

`stream_sessions`, `stream_events`, `audit_log` and `enforcement_log` have no
pruning. `bandwidth_samples` is kept for a year and `task_runs` is capped per
task, so the pattern exists and these were simply never given it. Not urgent
at any volume seen so far, which is why it has not been done, but it is the
kind of thing noticed two years late.

---

## Trusting more than a device

Trusted devices shipped: a tick on the Endpoints screen beside the ban
control, a suggestion for the devices with a settled history on one account
and none on any other, and a pair test in the travel and concurrent checks so
a signal is not raised when both ends are trusted devices of that account.

What was left open, and why.

**Trusting an account, or an address.** An address is the more tempting of the
two because a home address is stable and trusting it would quiet a whole
household at once. It is also exactly what a shared password looks like from
the outside, which is the thing the signal exists to find. Device first was
the right order; whether an address ever earns the same treatment should wait
until the device flag has been used for a while and the remaining noise can be
looked at rather than guessed at.

**Whether trust should go stale.** A device not seen for a year is not
obviously still theirs. The date is recorded so this can be answered later
without a migration, and nothing reads it yet.

**Whether a trusted device should be exempt from anything else.** Nothing has
suggested itself. The flag means one thing and says so in the model, which is
worth keeping until a second use proves itself rather than widening the
meaning on the strength of a hunch.

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
losing what it recorded before this app was watching. Nothing starts one
today: there is no button, no progress and no record that it ever ran. Until
there is, choosing Plex quietly means choosing to have only what happens from
now on, which is not a choice anybody would make knowingly.

What it needs:

- A button in Settings, under the source choice, that says how far back it
  will go and what it will bring. It runs in the background like the other
  jobs, reports progress on Tasks, and can be run again without doubling
  anything.
- A record of what the last import covered: when it ran, the span of dates it
  asked for, how many plays it read, how many were new and how many were
  already here. Without that, running it twice is an act of faith.
- Switching the source to Plex should say, there and then, that older history
  comes from Tautulli and offer the import. Nobody should have to read this
  file to find that out.

It brings only what is missing. Importing what is already here would double
every figure in the app, so the import has to recognise a play it already
holds and skip it, and running it twice has to be safe and boring. The upsert
the library scan uses is the pattern: the same row arriving again changes
nothing.

Which makes the more useful half of this a question rather than a copy: what
does Tautulli have that this app does not? Answering it is most of the work
and is worth having on its own, because it is also the check that the import
worked.

- Compare the two, day by day, over the whole of Tautulli's history: how many
  plays it recorded against how many are here. A day that matches is done. A
  day short by three is the thing to go and fetch.
- Say where the gaps are and how big, before importing anything. A missing
  week in 2022 and a missing hour last Tuesday are different problems: one is
  Tautulli's history being older than this app, the other is something having
  gone wrong recently and worth knowing about.
- Fetch only those days, and compare again afterwards. An import that says it
  read 4,000 plays is not evidence of anything; a gap report that comes back
  empty is.
- Run the comparison on its own, without importing, whenever anybody asks. It
  is the only honest answer to "is anything missing".

The care needed is play identity. A paused and resumed play is one play, and
the import has to agree with how plays are already counted here or every
figure in the app moves. Reference ids exist for exactly this and the import
should use them, both for recognising a play already held and for counting a
day, rather than inventing a rule.

### Checking the handover actually worked

Switching the source is the one change in this app where everything can look
normal and be wrong. The rows keep arriving, the pages keep drawing, and a
field that is quietly missing shows as a blank rather than an error.

So the switch needs something that says, in one place, whether the two sources
agree:

- Over the same recent window, the plays, the people and the devices each
  source reports, side by side.
- Which fields come back empty from the new source and did not from the old
  one, named rather than counted.
- A sample play looked up in both, field by field, because a number matching
  in total says nothing about whether the right value landed in the right
  column.

This is the test that would have caught the transcode decision mismatch, and
it is cheap: both sources are already readable through one shape.

### Users and libraries from Plex

Still read through Tautulli. Plex knows both. Lower value than the two above
because the slow sync runs rarely and nothing is waiting on it.

---

## Issues as the system of record, and the screen for it

Issues raised here are already kept here. Two things are missing: the screen
is not yet what it should be, and there is no way to bring in what Seerr
holds.

### The screen

Done in 0.89.0, against Seerr's list as the reference. A row carries the
artwork, the title with its episode number kept whatever gives way, the one
thing that is wrong, and the reporter's plays beside everybody else's, which
answers whether it is the file or the person before anything is opened. An
admin resolves from the row. A viewer sees their own reports and their own
plays, and is told whether the file is there without being told where.

Left for later: a report that was resolved by replacing the file could say so
on its row, since the replacements feature already knows when a new file
landed.

### Importing from Seerr

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

---

## Smaller things noticed and not done

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
