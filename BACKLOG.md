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
- **A date written into a test expires.** A test of "what has run in the last
  forty eight hours" was given timestamps on a fixed day. It passed when it was
  written and failed the next morning, with an error that says nothing about
  the cause. Where the code under test counts back from now, the test has to
  count back from now too. Fixed dates are fine where both sides of the
  comparison are fixed, which is most of them.
- **Measure before optimising, and after.** More than once the obvious cause
  was not the cause: the index that did not help, the test suite whose cost was
  the scheduler rather than the fixtures, the poster slowness that was the
  handshake. Every performance claim in the changelog has a number behind it
  because every one of them was checked.

### Working practice

- Nothing ships without the full test suite passing, a sweep of every page in a
  real browser, and a scan of the diff for anything personal.
- The browser sweep is done twice: once at a desktop width, listening for
  console errors, failed requests and React warnings, and once at 375 wide
  asking only whether the document is wider than the window. The second one
  found two pages that pushed every other page sideways, and neither was
  visible in a screenshot. The check is one line, `scrollWidth > clientWidth`
  on the document, and it is worth running on every page after any layout
  change.
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

### What an install on Plex alone still reads from Tautulli

Nothing, as of the people list and the libraries coming from Plex too. Plays
are recorded from Plex as they finish, the scan and the tracks read from Plex,
and everyone the server is shared with is listed whether or not they have ever
pressed play.

What remains true is the one thing Plex cannot answer: the address against a
play from before this app was watching. That is why Tautulli is an import
rather than a dependency, and why the check that nothing is missing exists.

A play recorded here has a negative id, so it can never meet one of
Tautulli's. Connecting Tautulli later removes any play of ours it also
delivers, matched by person, item and a start within two minutes. The import
of older plays, when it is built, should match the same way.

### The scan walks shows one at a time

The Plex scan walks shows one at a time, a request each, in one worker
thread. At about ten milliseconds a request that is fine for a scan every six
hours, so it was left simple. If a very large TV library makes it slow, list
episodes a section at a time instead, which is one paged listing rather than a
request per show, after checking against a real server that the listing
carries the show and season keys.

---

## What else Plex has, now that it is asked directly

Every number here was measured against a real server with roughly 31,000
files, 48 accounts and four years of history. They are written down because
the useful ones are not the ones that were expected.

**A websocket it pushes events to.** Done. The poll is untouched and remains
the floor; the socket only asks it to run now rather than in a moment, so a
websocket that dies quietly costs nothing but the speed it was added for.

The difficulty was not the connection, which took no new dependency. It was
telling a stream that just started from one carrying on: every playing stream
pings about every ten seconds with its position and that ping says "playing",
exactly as a new stream does. Waking on all of them asked the enforcer to run
constantly for no new information, which is worse than the poll it improves
on. The last state of each session is kept and only a change counts. Measured
on a real server with streams running: one nudge in ninety seconds, against
one every ten seconds before the fix.

**Four years of its own bandwidth figures.** Done, as a report. Per account,
per device, local apart from remote, a day at a time: 31,733 rows covering
1,445 days and 34.5 TB on the server it was written against. It went into the
reports engine rather than onto a page of its own, so the grouping, the
charting and the spans were already built, and the question it was wanted for
is answered by picking a measure and a grouping like any other.

Two ids needed mapping and both were measured: Plex calls the owner 1 against
the server while everybody else is already the account id this app files plays
under, and the figures carry Plex's own device number rather than the client
identifier everything else keys on.

**602 devices it remembers**, with name, platform, a client identifier on 601
of them, and a created date. That created date is a real first-seen, where the
app currently infers one from the first play it happens to have. Relevant to
trusted devices and to the new device alert.

**Intro and credit markers**, on 14 of 16 episodes checked, and chapters. No
use has suggested itself, which is why nothing was built; noted so the next
person does not go looking for whether they exist.

**624 collections**, recently added, on deck, 48 accounts, 33 shares, the 174
server settings, the maintenance tasks and whatever the server is doing right
now. All readable, none used.

**What Plex's history does not have**, checked rather than assumed: no IP
address, no transcode decision, no duration watched, no view offset. It does
have the device id, which maps to the client identifier a ban is written
against, so historical device attribution is available directly and only the
address is not. That single gap is the whole reason Tautulli is still needed,
and it is why the import is an import rather than a dependency.

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

Mostly already true, which was worth finding out before building it again.
The history sync pages through everything Tautulli has on its first run and
writes with an upsert keyed on Tautulli's own row id, so a play that is
already here changes nothing when it arrives a second time. There was never a
separate import to write; what was missing was a way to ask whether it had
worked.

That is now the "Check nothing is missing" task. It counts, day by day across
the whole of Tautulli's history, what Tautulli recorded against what is here,
and fetches only the days that are short, one request per day rather than a
walk through four years. Run against this install: 2,000 days compared, 19,046
plays on each side, nothing missing and nothing counted twice.

It is a button as well as a task, in Settings under the source choice, and it
answers where you are standing rather than starting a job and leaving you to
go and find the result. Where days are short it names them and offers to fetch
exactly those.

### Checking the handover actually worked

Done, as "Compare the two sources" beside the other check in Settings. It asks
both sources about the same twenty five files and compares sixteen fields on
each, and about whatever is playing and compares fourteen fields on each
stream, naming the fields that disagree and the fields one source leaves empty
rather than returning a score. Empty and wrong are reported apart, because a
field Plex does not fill is something to fetch and a field with the wrong
value in it is actively lying.

Run against this install: 25 files, 16 fields each, no disagreements and
nothing empty on either side.

It would have caught the transcode decision, and there is a test that says so
by feeding it that exact case: a session one source called a copy and the
other called a transcode.

What is left is a judgement rather than work: the file sample is twenty five
because each one is a request to Tautulli, which has no batch form. That is
enough to find a field that is wrong everywhere, which is what this is for,
and not enough to find the one item in ten thousand that differs. If that ever
matters, the sample is one number.

---

## Issues as the system of record, and the screen for it

Issues raised here are kept here, and what Seerr holds is brought in.

### The screen

Done in 0.89.0, against Seerr's list as the reference. A row carries the
artwork, the title with its episode number kept whatever gives way, the one
thing that is wrong, and the reporter's plays beside everybody else's, which
answers whether it is the file or the person before anything is opened. An
admin resolves from the row. A viewer sees their own reports and their own
plays, and is told whether the file is there without being told where.

A report closed by a replacement says Replaced on its row, since 0.116.0.

### Importing from Seerr

Done in 0.108.0. The five minute sync already read Seerr's issues; what it
lacked was a way to place a report whose rating key had gone stale, a reach
past Seerr's first page, and a memory: a report Seerr stopped listing was
deleted here with its notes. A report is now placed by rating key, then by the
TMDB, TVDB or IMDb id, then for a show by name, and kept when Seerr drops it.
Settings, beside Seerr, brings everything in on demand and says what it read,
what was new, what was already here and what it could not place.

Left for later: a report placed by name alone is a guess when two shows share
one, and is left unplaced rather than guessed. If that turns out common, the
first air date Seerr's title lookup returns is the next thing to match on.

Requests are a separate thing and stay with Seerr for now. Replacing those
means becoming the thing that talks to Radarr and Sonarr about wanting
something that does not exist yet, which is a larger job than reading a list.

---

## Worth building, and what each is worth

Written after a night of asking the real server what it has and timing the
answers. Ordered by what they are worth rather than by how hard they are, and
each says the number it rests on so the ordering can be argued with.

### What somebody is partway through

Not a Plex question at all, which was worth finding out before building
anything: history already carries how far into a thing each play got, and
twenty nine people on this server have something between five and eighty five
per cent finished in the last ninety days. The data is here and there is no
screen for it.

Two things it is worth for. The obvious one is a list of what each person has
not finished, which is what every other media app leads with and this one
cannot show.

The useful one for a tool about managing a server is the other way round: do
not suggest deleting a file somebody is halfway through. The cleanup lists
work from whether a thing has been played and when, and a part finished
episode looks exactly like an abandoned one.

### What a stream is actually doing to the server

Plex reports whether hardware was asked for and whether it was granted, which
this app already keeps per stream. What it does not keep is the server's own
load at the time. Plex's /statistics/resources came back empty on this server,
so there is nothing to read; the minute samples this app takes are the only
source and they do not include CPU. Worth a look only if that endpoint starts
answering.

### Collections, as a thing you can act on

624 of them on this server, now readable as a report grouping. The step beyond
reporting is acting: a rule or a tidy that applies to a collection rather than
to a file, which is how somebody thinks about their library.

### The library's own hubs

Recently added, on deck and continue watching are all answerable in one
request each. Worth it only alongside the watch state above, since on deck
without per person state is the server's deck rather than anybody's.

### Reducing what is read twice

The library scan and the file details both walk the whole library. The scan
lists every item and the details then ask about each one again in batches of a
hundred. Measured: the scan is 43 seconds for 31,250 items, the details about
ten milliseconds a file. Nothing is wrong, but the second pass is asking Plex
for things the first pass already had, and a single pass would halve the work.

Left alone because the two run on different timers for good reasons, and a
scan that also read every track would be a scan nobody could run quickly.

---

## The house style, applied everywhere

A row about a title now carries its artwork, a poster, the facts as label and
value and one clear action. Issues uses it, and components/TitleRow.tsx is the
same row for everywhere else: a person's most watched and recent plays, an
address's titles and a place's plays on the Map. Reports put the poster beside
a title. Every text box and select now stands at the control height, which
they did not before. Not yet done the same way: the Dashboard's lower half and
Settings.

---

## Holes in a season, and files kept twice

Both shipped, and both were sitting in what the scan already writes down. The
useful part is what had to be left out rather than what went in.

**A season still going out.** The first version compared against anything
other than the last episode present, which reports five missing episodes every
week of every running season. Only a hole between two episodes that are here
counts. That also means a show whose first episode was never filed reads as
complete, which is the right trade: a false "nothing missing" is quiet and a
false "five missing" is noise on every row.

**Double episodes.** Plex files "S01E01-E02" under index 1, so a complete
season reads as every second file gone. A season whose holes all sit alone
between two episodes, and which has about as many holes as episodes, is
counted separately and said to be, because a judgement nobody is told about is
indistinguishable from a bug. Measured: eleven seasons and 187 of 1,572
apparent holes. A season mostly that shape with a real gap in it still appears,
and carries the count of which holes are which.

**A show numbered absolutely.** The noisiest rows are long running shows where
a season spans episodes 17 to 88 and seven are here. That is true of what is on
disk and the row says what it covers, but the ordering puts them first. If that
turns out to annoy, the thing to try is Plex's own season leaf count rather
than a better inference from the numbers.

**What the sizes cost.** media_items keeps one file per item, because every
other thing built on it asks about one. Rather than widen the table and
migrate, the few dozen items with several files are asked of Plex when the page
opens, in the same batched form the details use. Fewer than two known sizes is
reported as not known rather than as zero, because zero reads as "nothing to
gain here".

**Not built: an action.** The list shows both paths and leaves the deleting to
a person. Wiring it to the tidy queue would mean deleting a file nobody asked
about on the strength of an inference, which is a different kind of feature and
wants more thought than a night. Deleting a file the person has picked, from
the row that shows both paths, is a different question and a reasonable one;
it is a policy decision about what this app is allowed to do rather than a
piece of work, and it should be asked rather than assumed.

**Not built: asking Sonarr to find the missing episodes.** The obvious close of
the loop, and the integration already searches for one episode by its show's
TVDB id, so a season's worth is `EpisodeSearch` with a list of ids instead of
one. It was left alone because there is no Sonarr connected to this install to
check it against, and three things would be guesses: whether `EpisodeSearch`
respects monitoring in the version somebody is running, what Sonarr says about
an episode number it does not list at all (which is the double episode case
again, and probably the common one), and whether a season Sonarr numbers
differently lines up with Plex's numbering at all. Writing it blind against the
documentation would put a button in front of somebody that quietly does
nothing. This belongs with Tdarr and Trakt, below, waiting on an instance.

## What the server is doing for itself

Shipped as a record and as two places that show it, and deliberately not as a
verdict.

Plex lists what is running at `/activities` and keeps no history: a scan at
three in the morning left no trace anywhere. What is kept is a spell, one row
per job keyed on Plex's own uuid, with a first and a last sighting, so "was the
server busy while this stalled" is a range rather than a trawl through a sample
a minute. It rides on the stream poll because reading it costs about six
milliseconds and the answer is usually that nothing is running.

The shape was measured by asking for a scan and watching: type
`library.update.section`, a title like "Scanning Movies", a subtitle naming
the item it is on, a progress percentage, and a Context child carrying the
library's number.

**What was not built, and the number to check before building it.** The obvious
next step is a stall cause: a stall while the server was scanning is a stall
with an explanation, and the cause list currently has to call that one "server
side, others stalled too" or "one-off so far". It was left alone because
nobody knows yet how often this server is busy at all. If it turns out that
something of Plex's own is running most of the time, a cause keyed on it would
relabel nearly every stall and say nothing. The figure to look at after a week
is what share of stalls fall inside a spell against what share of all time the
spells cover. Only a clear gap between those two is worth a cause.

**What it costs to ask.** Measured against the real server with the app
running: what the server is doing, 11 ms; the collections list, 7 ms; the
seasons with holes in them, 250 ms for 26,908 episode rows read and grouped;
and what is here twice, 530 ms including a round trip to Plex for the few
dozen items with several files. Nothing here needs making faster.

**What the live line cannot do.** A scan of a small library finished in six
seconds on the server this was written against, which is shorter than any sane
poll of a page, so the Dashboard line misses the short ones. That is the right
trade, and the ones it misses are not what made anything buffer. Everything
that ran at all is written down on the stream poll and listed under Storage.

## Collections, now that something reads them

510 of them on this install, written down by the scan since the tags table
existed and read by nothing but a report grouping. The first thing built on
them is the one that needed no new data and answers a real question: never
suggest deleting anything in these.

It works because the cleanup list measures the only thing it can, which is how
a file has been played, and a collection is where somebody has already written
down what they care about. Keeping one file at a time was already there and
does not scale: forty films is forty clicks, and another each time one of them
ages past the threshold.

What has been built on them:

- **A collection's own health**: 0.116.0, under Library, Collections. It reads
  the library once and indexes it, because of the collection that is most of a
  library.
- **A tidy scoped to a collection**: 0.118.0. `POST /api/library/tidy/many`
  takes a `collection` beside the `kind` it already took, and everything past
  working out the keys is the same code. Tidy all sits on each row of Library,
  Collections. It turned out to be the same code with a different source of
  keys, as expected, with two things worth having written down:
  - The cap could not be the list's cap. An attention list is ordered worst
    first, so cutting it to two hundred is taking the two hundred worth doing;
    a collection is ordered by nothing of the sort, so one over the cap is
    refused by name and told where to go instead. On this install the
    Spider-Verse collection is refused and every other one fits.
  - The keys come through the grandparent, the way the kept collections lookup
    already does, because Plex files a collection against a film or a show and
    never against an episode.
- **A rule scoped to a collection**: 0.118.0. A `collection` condition type
  with `is in` and `is not in`, one indexed lookup against media_tags per item.
  It had to be its own type rather than another choice field: for a country,
  no value means nobody knows where somebody is and neither answer is
  evidence, while for a collection it means the lookup ran and found none, so
  `is not in` has to be true of a film in no collection. An item with no
  rating key at all still matches neither way. Offered to stream, file and
  report rules, which meant the file and report subjects had to start carrying
  the keys above the file as well as their own.

Worth knowing before building anything else on them: the largest collection on
this install holds 1,727 titles and the next holds 42, so anything that walks a
collection has to cope with one that is most of a library.

Still open:

- **Nothing reads a collection on a show yet on this install.** Every one of
  the 511 is filed against films, so the grandparent path is covered by tests
  and by nothing else. The first show collection somebody makes is worth
  checking by hand.
- **A collection cannot be acted on from a rule.** A rule can ask whether
  something is in one; it cannot be told to tidy one, or to keep one. The
  kept collections setting is still a separate list of names typed into
  Settings rather than something a rule expresses.
- **The tidy has no way to do the next lot.** Over the cap, the answer is the
  Messy files list rather than a second page of the collection.

## Smaller things noticed and not done

- **A weekly digest exists and is off by default.** Worth revisiting whether
  anything else belongs in it once it has been run for a few weeks. The server
  unreachable alert and the disk warning are both candidates for a line in it.
- **The attention list is not in the house style.** It still draws a small
  poster beside a block of text, where everything else about a title now
  carries its artwork across the row. It is the list most often looked at,
  which is an argument both ways: worth doing, and worth not breaking.
- **A person's recap is not in the weekly digest.** The Recap tab has the
  numbers; a line per person in the digest would be the obvious second use.

---

## Looked at, measured, and not worth building

Recorded so that nobody has the idea again and spends a night proving the same
thing. Both of these sound good; the data does not support either.

### Intro and credit markers, to make "finished" exact

Several figures here treat percent complete as a proxy for watched, with
eighty five per cent as the line. Plex knows exactly where the credits start,
and asking for markers is nearly free: 200 milliseconds against 173 for fifty
episodes in one request, which is the same request the tracks already come
from.

It would change nothing. Measured across 142 episodes with a credits marker:
the credits start at a median of 93 per cent, the earliest anywhere was 88,
and not one of them started before 85. The threshold is already below every
marker on this library, so storing them would buy precision nobody could
observe.

Worth revisiting only for a library whose outros are much longer, where the
measurement would come out differently. The number to check is how many
episodes have credits beginning before the threshold; here it was zero.

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
- **Searching Sonarr for the episodes a season is missing.** Nothing to build
  against: no Sonarr is connected to this install, and the three things that
  decide whether it works at all cannot be checked from the documentation. See
  the holes section above for what they are.
