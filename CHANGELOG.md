# Changelog

Newest first. Each version is a heading with its date, then what was added,
changed and fixed. Settings, About reads this file, and compares it with the
copy on GitHub to say what an update brings.

## 0.101.2 - 2026-10-07

### Changed
- Artwork comes from Plex where there is a Plex to ask. Tautulli's image proxy calls Plex's own resizer to do the
  work, so going through it was a hop for nothing, and a hop that cost: asked for the same 300 by 450 poster,
  Plex answers with a 300 by 450 JPEG of 37 kB and Tautulli answers with a PNG of 215 kB, having ignored the
  format it was asked for. Measured on a real page of thirty six posters: half a megabyte against nearly eight.
- Tautulli stays as the thing to try when Plex will not answer, so a server asleep or moved costs a slower poster
  rather than a broken page.

## 0.101.1 - 2026-10-07

### Changed
- A playing stream's position runs on between readings instead of sitting still and then jumping. It stops dead
  the moment the stream is not playing, and every reading from the server replaces the guess outright, so a seek
  or a pause lands on the next poll and the number is never more than one interval from the truth. The bar and
  the clock are worked out from the same number, so they cannot disagree.

## 0.101.0 - 2026-10-07

### Fixed
- A track ticked by hand is no longer thrown away by a Settings rule. Choosing to keep a French subtitle on a
  server set to keep English rewrote the file without it: the choice was applied and then the language filter ran
  afterwards and undid it. The same fault silently reordered the track chosen to play first. Winning now means
  the filter does not run at all on a kind somebody has chosen by hand, and it is per kind, so picking subtitles
  still leaves the audio rule alone.

### Changed
- The track picker is rebuilt around the thing a choice is actually made by. The language comes first and on its
  own, then what the track is, then whether it is forced, for the hard of hearing, the default, or carries its own
  name. Two rows reading "PGS eng" with nothing between them was a choice nobody could make, and all of that has
  been stored since 0.90.0 without the picker ever being given it.
- A language can be taken or dropped whole. A real file here has ninety subtitle tracks across thirty two
  languages, which is ninety tick boxes otherwise.
- Audio and subtitles are full width and stacked rather than two columns side by side. They are never the same
  length, so one column sat empty while the other scrolled in a third of the page.
- The steps now say which tracks they would drop, and the list shows those struck through. The panel used to read
  "Drop 79 subtitle tracks" above a list reading "keeping 90 of 90", both true and impossible to hold at once.

## 0.100.1 - 2026-10-06

### Fixed
- An error could come back as a red box with nothing in it, which is the one state worse than the app staying
  quiet: it says something went wrong and refuses to say what. The client read the server's explanation only when
  it was a single string, and a validation failure arrives as a list, so it fell through to the HTTP reason
  phrase, which is empty on HTTP/2 and therefore on every install behind a reverse proxy. A failure now names the
  fields it objected to, and when there is genuinely nothing to report it says so with the status rather than
  showing an empty box.

## 0.100.0 - 2026-10-06

### Added
- "Compare the two sources", beside the check that nothing is missing. It asks Plex and Tautulli about the same
  twenty five files and compares sixteen fields on each, and about whatever is playing and compares fourteen
  fields on each stream. Counting is not enough: a total agreeing says nothing about whether the right value
  reached the right column, which is how the transcode decision nearly went wrong, with both sources reporting the
  same stream and calling it different things.
- Fields that disagree and fields one source leaves empty are reported apart. A field Plex does not fill is
  something to go and fetch; a field with the wrong value in it is actively lying, and they are not the same
  problem.
- Nothing playing is said plainly rather than reported as agreement, because the second one would be believed.

### Changed
- The two checks stand on their own without a line of prose beside them, like the rest of Settings.

## 0.99.2 - 2026-10-06

### Changed
- Two tests closed a gap rather than fixing a fault: that an event from Plex reaches the enforcer, and that the
  enforcer is what it reaches. Neither could be seen on a running server unless somebody happened to be watching
  something, and the wiring between them is exactly the sort a merge changes quietly. Both were checked by
  breaking them on purpose first.

## 0.99.1 - 2026-10-06

### Fixed
- Fetching a day the check said was short could leave every play on it recorded twice. An install that ran on
  Plex alone writes its own plays down, and the history sync has always removed ours when Tautulli later delivers
  its copy. Filling a gap writes to the same table and was not doing that, so the day ended up holding both, and
  the next run of the check would have reported it as having more here than Tautulli has. Found by reading the
  two paths side by side rather than by it biting.

## 0.99.0 - 2026-10-06

### Added
- A report of what Plex measured each person's devices using, a day at a time, going back as far as Plex kept it.
  On a real server that is 1,445 days and 34.5 TB, four years before this app was installed. Nothing here could
  reach back like that: the minute by minute samples start at install, and Tautulli never had the figures at all,
  since it only knows what it was running to watch.
- Local traffic is counted apart from remote, because remote is the figure an upload has to carry and the two
  added together answer neither question. Grouped by person, by device, or by either against the other, over any
  span, in the same reports screen as everything else.

## 0.98.0 - 2026-10-06

### Added
- The check that nothing is missing is a button in Settings, under the source choice, as well as a nightly task.
  It answers where you are standing rather than starting a job and leaving you to find the result: on a four year
  library it comes back in under a second with the count on each side. Where days are short it names them and
  offers to fetch exactly those.

### Fixed
- The guard against a route being swallowed by one with a placeholder in it was checking nothing. It walked the
  app's routes, which hold a wrapper per included router rather than the routes themselves, so it passed with the
  bug it was written for deliberately put back. It now flattens them, counts what it saw, and fails on that bug.
  The fault it missed was real: one router's /history/check was being caught by another's /history/{row_id}.

## 0.97.0 - 2026-10-06

### Added
- With no Tautulli, the people list and the libraries come from Plex. Everyone the server is shared with is
  listed, with their name, email and which libraries they can see, whether or not they have ever pressed play.
  Before this, somebody shared with was unknown until they watched something.
- Which leaves nothing on an install with Plex alone that still needs Tautulli, except the one thing Plex cannot
  answer: the address against a play from before this app was watching.

### Fixed
- Somebody taken off the share keeps their row and their history. Two people on a real server are in the user
  list and no longer on the share list, and a row vanishing would orphan four years of plays.

## 0.96.0 - 2026-10-06

### Added
- A "Check nothing is missing" task. It counts, day by day across the whole of Tautulli's history, what Tautulli
  recorded against what is here, and names any day that is short. Run against a real install: 2,000 days
  compared, 19,046 plays on each side, in under a second.
- Where a day is short it fetches that day and nothing else, one request per day rather than a walk through four
  years. Running it twice is safe and boring, because history is keyed on Tautulli's own row id and written with
  an upsert, so a play already here arrives with the id it already has.
- Days with more plays here than Tautulli has are reported separately rather than ignored. On their own they are
  expected, since this app records from Plex directly when Tautulli is not connected, but a lot of them on days
  Tautulli was running is what counting something twice looks like.

## 0.95.0 - 2026-10-06

### Added
- Plex now tells this app when something starts, stops or pauses, instead of being asked every five seconds. A
  banned device used to keep playing until the next poll came round; now the check runs the moment Plex says
  something happened.
- The poll is unchanged and still runs on its timer. The socket only asks it to run sooner, so a connection that
  drops costs nothing but the speed, and it reconnects by itself. No new dependency: the websockets library was
  already here.
- Only a real change wakes it. Every playing stream pings about every ten seconds with its position, and that
  ping says "playing" exactly as a new stream does, so the last state of each session is kept and only a
  difference counts. Measured on a real server with streams running: one check in ninety seconds, against one
  every ten seconds before that was sorted out.
- With no Tautulli, plays are recorded from Plex as they finish. History, the map, Endpoints and the sharing
  signals fill as people watch, where before they stayed empty for ever on an install connected to Plex alone.
  Counted the way the Tautulli sync counts: one play per Plex session, a pause inside it still one play, nothing
  under thirty seconds, and the time paused not counted as watched.
- Anybody who plays has a name, from what Plex says with each stream, without Tautulli to list the users.

### Changed
- A file's card in the Library reads in a glance. What is wrong with it is a line each, opening to the why and the
  fix. The facts are label and value on one line each, the file is named by its name with the folders in its
  tooltip, and a file nobody has played says so instead of "0 times by 0 people". The tracks are listed once.
- One or two things to do, with the obvious one marked: finding a replacement when something is wrong, tidying
  when only the tracks are untidy. Asking Radarr or Sonarr to search by itself, or to tag the file, are words
  under them rather than two more buttons.
- Tidying opens when asked for rather than standing open on every file. Its steps are lines to tick with their
  reasons under them, its tick boxes are the track list rather than a second copy of it, and keeping all, none or
  one language's subtitles is one control at one height. The button says how many tracks it is about to drop.

### Fixed
- Connecting Tautulli to an install that had been recording from Plex would have counted the plays both had seen
  twice. A play Tautulli delivers that was already recorded here, by the same person, of the same thing,
  starting within two minutes, is kept once, as Tautulli's.

## 0.94.0 - 2026-10-06

### Added
- Devices can be trusted. A green tick on the Endpoints screen, beside the ban control, says this device belongs
  to this account.
- Trusting quiets one thing: a pair of plays is not raised as one account in two places when the device at each
  end is a trusted device of that account. A phone on mobile data, a laptop carried to work, a VPN whose exit
  moves between cities are the ordinary life of a household, and the signal had no way to tell them from sharing.
- Both ends, never one. A trusted device playing alongside one nobody recognises is the case most worth seeing,
  so trusting half a pair leaves the signal standing. There is a test for each of those three, and a fourth that
  the signal still fires when neither device is trusted, since a rule that quiets a signal looks exactly like a
  rule that never fired.
- Nobody is going to tick two hundred devices, so the ones with a settled history on one account and none on any
  other can be trusted in one go. On a real library that offered 82 of 234. The tick stays the final word: any of
  them can be untrusted afterwards.
- Trust is per account, because a device is one row per account that has used it. A shared television trusted for
  the person who owns it says nothing about the person who signed into it afterwards.

## 0.93.0 - 2026-10-06

### Fixed
- The facts on a stream card read properly on a phone. A rule meant for a middling window had a ceiling and no
  floor, so it also beat the single column a narrow card is supposed to get: a phone was drawn two columns about
  190 and 140 pixels wide, an address with its city on it wrapped to five lines, and the facts beside it lined up
  with nothing. Nothing ever ran off the screen, which is why looking for that never found it.
- The map's own zoom buttons were 29 pixels square and the Key pill was 33, against the 32 every other control in
  the app shares. Measured across all twelve pages at desktop and phone width, every input, select and button is
  now that height. The only things at another are the text links in History, which are links drawn as buttons and
  belong inline.

## 0.92.0 - 2026-10-06

### Changed
- Plex is the recommended connection, and Tautulli is optional. First run asks one question before anything else,
  connect to Plex directly or through Tautulli, and says what each brings. An install that answers Plex is never
  shown a Tautulli field and reaches the app with no Tautulli at all.
- Linking Plex needs no password. Setup shows a short code to enter at plex.tv/link, waits for Plex to confirm,
  and keeps the token on the server; it never comes back to the page. Pasting a token still works for anybody who
  has one. Finding the server is then done once and the address kept, since looking it up costs about twenty
  seconds and connecting to a known address a fifth of one.
- Settings calls Tautulli what it now is, the way to bring in your history, and lists Plex first.
- An opened report holds only what its row has no room for: the conversation, the play it was reported from,
  every play of the file one to a line, and the file itself in a few lines with what is known to be wrong with
  it. Replacing the file and rewriting its tracks stay in the Library, one click away.

### Fixed
- With live activity set to Plex, Now playing still asked Tautulli, so it stayed empty without it while the rules
  could see every stream. It reads from the same source as the rules now.
- Without Tautulli, a ban or a rule could not stop anything: stopping a stream, and knowing the server has the
  Plex Pass it needs, both went through Tautulli. Both come from Plex when Plex is the source.
- Without Tautulli there was no artwork anywhere. Posters and backgrounds come from Plex's own resizer when
  Tautulli is not connected, with the token sent as a header rather than in the address.
- The library scan and the reading of file details each built a Tautulli client even when reading from Plex, and
  the jobs that only Tautulli can do failed every few minutes on an install without it. They now say plainly
  that Tautulli is not connected.
- Comments read in from Seerr said "Someone" rather than who wrote them. Seerr does not always send the whole user
  with a comment, and a sync with nothing new to read was replacing named comments with unnamed ones. Names are
  now kept, filled in from the Plex users this app knows, and the first comment, which Seerr always makes the
  reporter's, is signed by the reporter.
- A film reported in Seerr read as "Special, episode 0", from the season and episode Seerr sends for a film.

## 0.91.0 - 2026-10-06

### Fixed
- Turning off Run rules no longer turns off the ban list. Bans are enforced by the same sweep that runs the
  rules, and the switch returned before that sweep had even assembled them, so quietening one noisy rule
  silently stopped every ban on the server with nothing anywhere saying so. Run rules now governs the rules
  somebody wrote. The ban list and the blocked countries are explicit acts against a named device, address or
  place, each already has its own record only switch, and they keep working either way.

### Added
- Four tables that grew forever are pruned: the record of each stream, the buffering during it, the audit log
  and the enforcement log. Bandwidth samples and task runs already had this, so the pattern existed and these
  were simply never given it.
- Two settings under Syncing say how long each is kept, three years by default, 0 to keep everything. It is a
  setting rather than a number in the code because a report can be asked for any window up to ten years, and
  throwing away old streams should be something you chose rather than something you found out.

## 0.90.0 - 2026-10-06

### Added
- Everything else Plex says about a track is kept now, not just the four things Tautulli passed on. An audio track
  also carries its channel layout, profile, sample rate, bit depth, whether it is the one a player picks by
  default, and its own name in the file. A subtitle also carries whether it is for the hard of hearing, whether it
  was written for a dub, whether it is the original language, whether it is the default, and its name.
- The channel layout is the useful one of those: 5.1(side) and 5.1(rear) are both six channels and are not the
  same thing, and the count alone could not say which a file had.
- Subtitles for the hard of hearing can be told apart from plain ones at last, which is the difference between
  subtitles and subtitles with every door slam written out. Found on 205 files in the first six thousand read.
- The library's track lists show all of it.

### Changed
- A field Plex did not mention is left out of the stored track rather than written down as a no, which is how Plex
  answers and what it means. It also keeps a library of thirty thousand files from storing tens of megabytes of
  falses. The four fields that were always there are still always there, so nothing reading them has to change.

## 0.89.0 - 2026-10-06

### Changed
- Issues, rebuilt around the question behind most reports: is it the file, or is it them? Each row puts the
  reporter's plays beside everybody else's, so somebody who stalled three times while two other people played it
  cleanly reads differently, at a glance, from a file that stalls for everyone.
- Resolving and reopening are on the row. Nothing asks first, because either one is undone with one click. A note
  typed in an opened report goes with the resolution, so saying what was done and closing it is one click too.
- A long title keeps its season and episode. Rows clipped "The Show - Episode" from the end, which could cut off
  the numbers that say which episode is being reported. They now shorten the way the stream tiles do: the
  episode's own name first, and the numbers never.
- An opened report reads as facts rather than a paragraph: the device, the network, how it played, how often it
  stalled and how much was watched, then the conversation, then every play of the file one to a line.
- Somebody who is not an admin sees their own reports, how their own plays went, and what is already known about
  the file, without the buttons that only an admin can use.
- The filters are buttons rather than a list to open, and every control on the page is one height. The kind of
  problem is chosen the same way when reporting one.

### Fixed
- A viewer opening their own report was sent where the file is kept on the server, which they are not meant to
  see. They are still told whether it is there.
- A report on a film Plex no longer has said so until its row was looked at, then stopped. Drawing the artwork
  asks Plex about the key, which leaves an empty placeholder row behind, and that row was being read as the film
  being back.
- In an opened report on a phone, the facts ran off the right edge of the screen.


## 0.88.0 - 2026-10-06

### Added
- With Plex chosen, the audio and subtitle tracks in every file are read from Plex as well, which was the last
  thing still going through Tautulli. Plex will not put tracks in a library listing, but it does answer for a
  hundred files in one request, which Tautulli's API has no form for at all. Measured on this library: 2,000 files
  in 19 seconds, against 636 ms a file through Tautulli, and 313 requests for the whole library against 31,250.
- Each track keeps what it kept before: the codec, channels, language and bitrate of every audio track, and the
  codec, language, whether it is forced and whether it sits in the file or beside it for every subtitle.

### Changed
- Nothing about what is stored. 400 files Tautulli had already described were read again from Plex and compared
  field by field: every audio track list and every subtitle track list matched exactly, and 21 other columns
  matched on all but a handful of files where Plex had been re-matched since Tautulli last looked. The dynamic
  range wording is Tautulli's own, worked out against every file in the library it had called anything other than
  SDR, so rules and reports that match on "HDR10" or "Dolby Vision" carry on working.

## 0.87.0 - 2026-10-06

### Added
- The library source setting now does what it says. With Plex chosen, the library scan reads every film and
  episode from Plex itself rather than through Tautulli, and stores the same rows, so Problem files, 4K copies,
  library sizes and everything else built on the scan carry on unchanged.
- A scan from Plex fills in the IMDb, TMDB and TVDB ids for the whole library at once. Before, they arrived one
  title at a time, and only once somebody played it, so deep links and request matching did nothing for anything
  unwatched.
- It also stores each file's path, which the on-disk check and tidying are built on.

### Changed
- A tile's title keeps the show, the season and the episode, and gives up the episode's name instead. It was the
  other way round, which left "Y... - S02 - E04": the two numbers, and not the one word that makes them mean
  anything. The show name now takes everything except the room the numbers need and a few characters of the name.
- Less air around the dashes in a title, on the tiles and on the stream card both.

### Fixed
- A request whose title had changed key could be matched by TMDB id to an unrelated episode. An episode's TMDB id
  is the episode's own, a different number from the film or show a request names, so episodes are no longer looked
  at. With every episode now carrying one, a coincidence was only a matter of time.

## 0.86.0 - 2026-10-05

### Fixed
- Live streams were not being recorded at all. Three hardware transcoding columns added in 0.84.0 are booleans,
  and Tautulli answers those questions with an empty string when it has nothing to say, which the column refuses,
  so every insert failed and the whole session was lost. An empty answer is now recorded as no answer, which is
  what it means: Tautulli not saying whether hardware was asked for is not the same as it saying no.
- The stream card in the map's popup had a scrollbar along the bottom. Two of its rules asked how wide the window
  was, and the popup is 460 pixels wide whatever the window is, so on any normal monitor it laid the facts out in
  two columns and refused to wrap an address with a city on it. The facts stack in a popup, and a value there can
  wrap.

### Changed
- Every explanation in Settings is folded away behind an information icon beside its heading. They are worth
  reading once and after that they were most of the page, with the controls somewhere underneath. Each one
  remembers whether it is open, so reading a page carefully does not mean opening the same notes next visit.
- The explanations themselves are shorter and plainer. They had grown into paragraphs arguing their own case.
- The Settings heading above Add account reads "Accounts" rather than "People", which is what it lists, and no
  longer reads as the tab now called Endpoints.


## 0.84.1 - 2026-10-05

### Changed
- Every part of a tile in Now playing goes where it names: the show, the season, the episode, the person and the
  device. The tile still opens when pressed anywhere else, by keyboard as well.
- An episode reads as "S02 - E03", and the episode's own name is part of its link, because two characters is a poor
  thing to aim at and the name is what is being pointed at.
- A title too long for its tile gives up the show name first and never the numbers. Clipping the whole line left
  "The Chosen - S01 - ...", which cuts off the part somebody is looking for.

## 0.84.0 - 2026-10-05

### Added
- The source switch is in Settings, under Plex and Tautulli, with Find servers to look the address up once and
  store it. The Plex test now says whether the stored address answers and how quickly, since that is what the live
  source depends on.
- A stream recorded from Plex keeps what Tautulli never reported: whether hardware transcoding was asked for and,
  separately, whether it was actually used to decode and to encode. Asked for and not granted is the case worth
  explaining, and a server doing none of it looked exactly like one that was never asked.
- Also kept: the video profile and frame rate, the real width and height, the audio channel count, the streaming
  protocol, and which audio and subtitle track was actually selected rather than which the file happens to contain.

## 0.83.0 - 2026-10-05

### Added
- Live activity can be read from Plex itself instead of through Tautulli, chosen by a setting. Plex answers in
  about nine milliseconds and carries the viewer's address, whether they are local, relayed and secure, the device,
  the player and the account, which is everything this app records about a stream. The whole sweep is roughly three
  times quicker.
- A Plex connection that is held rather than discovered. Asking plexapi to find the server takes twenty seconds,
  because it tries every address Plex advertises including ones unreachable from outside the house. Connecting to a
  known address takes a fifth of a second, so the address is found once and kept.

### Changed
- Both sources answer in the same shape, so nothing that reads a session knows which was asked. That includes the
  one word a session is judged by: a stream whose video is copied and whose audio is converted is a transcode, the
  way Tautulli has always reported it, because that is what every rule written here matches on.

## 0.82.0 - 2026-10-05

### Fixed
- Artwork is roughly four times quicker to arrive. Every image opened a new connection, and over HTTPS that is a
  new TLS handshake per picture. Measured against a real server: 230 ms an image that way, 54 ms sharing one client
  the way the services we fetch from have been doing all along. One client now, held open, rebuilt only when the
  settings it was made with change.

## 0.81.0 - 2026-10-05

### Added
- An issue says whether the file is still on the disk. The library's own row only records where the file was at the
  last scan, so it cannot answer this; the two disagree exactly when something has been deleted, moved or
  unmounted, which is the case worth knowing about. A path this container cannot reach is said differently from a
  file that has gone: one is a mount to fix, the other is a file to replace. A file that has changed size since the
  scan says so, because that is somebody having replaced it.
- A report whose key the library has no row for is matched by its id instead, so it names the title and says Plex
  has renumbered it rather than reading as "Item 87676".

### Changed
- Issues are rows about a title rather than boxes of text: the artwork bleeds across the row behind a scrim, with
  the poster, the year, the title, what was said, the facts as label and value, and one clear action. The first
  piece of a house style for every list that is about something with a picture.

## 0.80.0 - 2026-10-05

### Added
- Any combination of people, devices and addresses narrows the list you are looking at. Which addresses has this
  person played from, who has used this device, which devices were seen at this address, or all three at once. The
  list you are on is not offered as a filter on itself, and picking two of one kind means either of them.

### Fixed
- The Endpoints rename only reached the nav. The Home tiles, the ban dialog, the Rules page, a notification and the
  README all still said People. A tab is rendered through its label now, with a test to stop the two drifting again.
- The sidebar was too narrow for an address and its owner, so the list scrolled sideways and put the first digit of
  every address off the left edge. It is wider, it does not scroll sideways, and an address sits on two lines.

## 0.79.0 - 2026-10-05

### Added
- Addresses are a list of their own, beside Users and Devices. The detail view for an address already existed and
  already worked; there was simply no way in to it, which is why clicking an address anywhere went to the map
  instead. Five hundred of them in 75 ms, saying who used each, from where, on how many devices, and whether it is
  banned, including by a range rather than by name.

### Changed
- The People tab is called Endpoints, because it is about three things and not one: a person, a device and an
  address are three ways of asking the same question. Only the word changes. Every existing link, bookmark and
  stored tab keeps working, and a URL asking for Endpoints works too.

## 0.78.0 - 2026-10-05

### Added
- Every row under Requested, never watched has somewhere to go: its history here, and Plex, IMDb, TMDB, Trakt and
  Seerr. Built from what is already known, so a missing id means no button rather than one that goes nowhere. A row
  with no file behind it gets no Plex button, because a key Plex does not know lands on an error, but its ids still
  open the outside world.

## 0.77.0 - 2026-10-05

### Fixed
- Posters for shows and seasons were slow because finding the artwork was a full scan of every row in the library,
  once per picture. Asked as one query with an OR, SQLite preferred the media type index, which matches all 26,000
  episodes. Asked as two, each uses the key it was given: 32 ms a poster becomes 0.28 ms.
- An item with no artwork cost two calls to the media server and a 404 on every single visit, because nothing is
  written for a miss and the next visit asked again. A miss is now remembered for an hour.
- Opening a show left its seasons' posters queued behind the wall of shows that was already asking. The limit is
  wider, and a request the browser has dropped is no longer fetched for a page nobody is looking at.

## 0.76.1 - 2026-10-05

### Fixed
- The posters and list switch does something at the show and season levels. It was above both of them and changed
  nothing, because they were drawn as rows either way.

### Changed
- A file in the list view carries its poster, and the rows line up. It was a checkbox floating beside three stacked
  lines with no picture, nothing separating one row from the next, and a line of air between every line of every
  row, which over sixty rows is most of the page. A row is a third shorter and five fit where four did.

## 0.76.0 - 2026-10-05

### Fixed
- Requested, never watched mixed two different problems. Rows reading "Item 45848" with no title and no size were
  not requests nobody had watched: they are requests the service marks as available for a key the library has never
  seen, which means the file is not there. They have their own list now, because "nobody watched it" and "it is not
  here" ask for different things and the second is the more actionable.
- Two people asking for the same film made two rows, which is why the same item appeared twice. One row per title
  now, saying who else asked.
- A title whose key changed in Plex is found by its id instead, so it reads as a film rather than a number.

## 0.75.0 - 2026-10-05

### Added
- A title goes where it names. On a stream card the show opens that show, S01 opens that season and E07 opens that
  episode, each landing in the library at the right level. A film opens itself.

### Fixed
- Opening a show showed the previous show's episodes underneath its seasons. The episode list is not asked for
  above a season, but the last answer was still in hand and nothing told the page to stop drawing it.
- Shows and seasons have posters. Neither has a row in the library, because neither has a file, so the art is taken
  off one of their episodes, which do.

### Changed
- Slightly less blur on the artwork behind a card.

## 0.74.0 - 2026-10-05

### Added
- Television is browsed as show, season, episode. Browse offered twenty six thousand loose episodes and no way to
  say "that show". There is no row for a show or a season, because neither has a file, but every episode carries
  the keys and numbers that say where it belongs, so both levels are a grouping rather than something to fetch: 567
  shows out of the episodes in under two hundred milliseconds.
- A trail across the top says where you are and gets you back out. Films are untouched: they are a flat list and
  always were.

## 0.73.0 - 2026-10-05

### Added
- RUN_BACKGROUND_JOBS, which starts the app without its scheduler, its syncs or its boot-time probe. Every page
  still answers from what is already in the database. Meant for a second instance kept for reading, and for the
  test suite.

### Changed
- The test suite runs in about half the time. Every one of five hundred tests started a scheduler, which then fired
  a sync immediately, and waited out a capability probe against a host that does not exist: four hundred
  milliseconds each, for work no test wanted. The handful of tests that are about scheduling ask for it explicitly.

## 0.72.1 - 2026-10-05

### Changed
- A fact on the stream card is on one line again. Capping the columns stopped them stretching and started a long
  address wrapping inside its cap while short values left a gap, which read worse than the stretch did. The columns
  are sized to their contents and packed left now: one on a narrow card, two normally, three when there is the room,
  and nothing breaks in the middle.
- The user, the player and the address sit together at the top. They are the three things on the card that go
  somewhere, and they were scattered through the technical detail.
- The cards in the Now playing strip carry the blurred show as well, so the strip and the panel below it look like
  the same thing.

## 0.72.0 - 2026-10-05

### Fixed
- Clicking an address on a stream card opens that address. It opened the map, which is its own button at the foot of
  the same card, so there was no way to get from a stream to the address behind it.

### Changed
- The stream card reads at a glance on a wide screen. Its facts grid had two stretching columns, so a dozen short
  values were spread across two thousand pixels with their labels stranded at either end. The columns are capped and
  packed left, and a wide screen gets a third and fourth pair of them rather than more stretch.
- The show sits behind its own card, blurred far enough to be texture rather than a picture competing with the words
  on top of it, over a scrim so the contrast does not depend on what the artwork happens to be. The image proxy can
  now serve the wide backdrop art as well as the cover, cached separately and falling back to the cover.
- The player says what kind of thing it is: a television, a phone, a desktop, a console or a browser. A category
  rather than a brand, because the shape is the useful part at that size.

## 0.71.0 - 2026-10-05

### Added
- Filters on the Log: a date range, a person, a rule, an outcome, the area a change touched, and a search over
  titles and summaries. Three hundred entries on one timeline and the only control was which of the two tables to
  read.
- The dropdowns offer only what is actually in the log, so there is no picking a rule that never matched anything.

### Changed
- A filter one half of the timeline cannot answer narrows it to the other half rather than being ignored. Asking
  for one rule has no sensible answer among settings changes, so the changes drop out; asking which area a change
  touched drops the stream actions.
- The outcome a filter selects is worked out the same way the page draws its pill, so picking "stopped" returns
  exactly the rows that read "stopped". A test holds the two definitions together.

## 0.70.0 - 2026-10-04

### Changed
- A failed replacement says what went wrong once, in English. The reason appeared three times on one row, and the
  reason itself was the download client's raw status line: six fields, four of them saying NONE, one an unresolved
  placeholder. Only the fields that say something are kept, so a row that read "PAR Status: FAILURE - Unpack Status:
  NONE - Move Status: NONE - Script Status: {scriptStatus} - Delete Status: NONE - Mark Status: NONE" now reads
  "PAR Status: FAILURE".
- Opening a finished replacement no longer repeats its own heading. The row that expands drew the title, the kind
  and the release name, and the panel it expanded into drew all three again.
- One button instead of two that did the same thing. "Show what happened" and "Refresh" both just asked the service
  again; a failed row asks once when it is opened, so what happened is simply there, and Refresh is the only button.

## 0.69.1 - 2026-10-04

### Changed
- Now playing fills the row it is given. Four cards was a fixed number, so a wide screen showed four streams, half
  an empty strip and a tile saying one more was playing, which was the one thing there was obviously room for. The
  strip already works out its own columns, so the number of cards is now the browser's own answer rather than a
  second copy of the card width kept in the page code. Six streams on a wide monitor, two on a laptop, one row
  either way.

## 0.69.0 - 2026-10-04

### Fixed
- Bans are enforced. Two separate faults were stopping them, and between them they explain a banned device or
  address carrying on playing.
- The ban list now acts unless you say otherwise. Its switch started unset, and unset fell through to the old global
  dry run flag, which starts on, so on a default install every ban only recorded what it would have done. A ban is
  not a rule: somebody opened a dialog, named one device, typed a reason and chose how long, and reading that as
  "record it and let the stream carry on" is the feature quietly not working. The environment safety lock still
  overrides it, which is what that is for, and asking for record only is still honoured.
- A banned address took the country list's record only setting instead of the ban list's. The address rule is given
  a negative id so its cooldown stays stable between sweeps, and the code decided what a rule was by testing only
  whether that id was negative, which the country rules are too. So a banned address never stopped anything unless
  the country list happened to be set to act as well.

## 0.68.1 - 2026-10-04

### Fixed
- A ban made while a device was streaming for the first time recorded a slice of the machine id as its name and
  attached the ban to nobody, so it did not count against that person anywhere the app counts bans per person.
  Banning never needed the device to exist and still does not, but now that a streaming device is written down the
  ban gets its real name and its user. Covered by a test.

## 0.68.0 - 2026-10-04

### Fixed
- Clicking the player name of something playing right now said "No such device". The device inventory is rebuilt
  from finished plays, and a device playing for the first time has not finished one, so it had no page to open. A
  device is now written down the moment it starts a stream. It also means a new device can be reviewed while it is
  playing, rather than hours later, which is the moment worth knowing about.

### Changed
- The remediation queue is one list. Tidying a file and replacing it are the same question asked about the same
  file, and they were two sections with two headings, so what you queued a minute ago sat above or below the other
  list depending only on which kind of work it was. Newest first, each row saying which kind it is.
- The queue's opening paragraph is a line. It was four lines of explanation above everything else on the page.

## 0.67.0 - 2026-10-04

### Changed
- One scale for text and space, and one height for every control. Six button styles sat at four different heights,
  so a row holding more than one of them stepped up and down across the page. Buttons, chips, segmented controls,
  selects and inputs are all 32 pixels now and centre what is inside them.
- Files worth attention reads like the rest of the app. Every row carries its poster, the reason it is in the list
  is the coloured thing rather than another line of grey, and the word "Details" at the far right is a control that
  looks like it opens.
- "Keep it, stop asking" moved into the row. It had a full width band of its own under every file, which was a
  second strip of furniture per file and doubled the height of a list of two hundred.
- A count is not a notice. "200 files, worst first" was in the same boxed note the app uses to warn you about
  something.

## 0.66.0 - 2026-10-04

### Changed
- The app asks its own questions. Thirty one places called the browser's confirm, prompt or alert, which arrive in
  the wrong typeface in the wrong place, say "127.0.0.1:6277 says" above the question, cannot show a warning in red
  or a file size, and on some browsers carry a tickbox that silently turns every later question into a no. There is
  one dialog now, in the app's own style, and a test that stops another creeping back in.
- Three of those questions are gone rather than replaced. Searching for a replacement, tagging a title for later,
  and tagging a batch of them all asked about something reversible and said so in their own text, which makes a
  step that is only ever clicked through, and teaches people to click through the ones that matter. Downloading a
  chosen release no longer asks either: the picker already shows the release and now says what will happen to it.

## 0.65.0 - 2026-10-04

### Added
- Space, on the Library overview: what each library takes, how many files, and what it has gained or lost over the
  week and the month. Nothing anywhere recorded when a file arrived, so the scan now writes down what each library
  holds once a day and the change is measured from that. The page says how many days it has so far rather than
  claiming a figure it cannot support, and a library with no history reads as "no history yet" rather than
  "unchanged", which are different answers.
- How much room is left, on the Storage page. Read from the disks the media is mounted on, grouped by the device
  underneath, so two stores on one share get one answer between them and are told they are sharing it. The bar
  turns when a disk passes 90%. Nothing to show when the media is not mounted into the container, which is a normal
  way to run this and not an error.

## 0.64.0 - 2026-10-04

### Added
- A Content-Security-Policy on every response. The other three security headers were already set and this was the
  missing one. There is nothing to exploit today, since the front end never writes HTML it was handed, but the page
  does render library titles, player names and the text an indexer sent back, and all of those come from outside.
  The policy names the basemap host, because a policy that forgets it is a policy that leaves the map blank.
- Setup shows what time the server thinks it is. It asks for Tautulli and tests it, asks for MaxMind and tests
  that, and never mentioned the one thing it cannot test for you: TZ decides what every time-of-day rule means, and
  a wrong one is silent for ever.
- Settings says so when the app is being read over HTTPS and the session cookie's HTTPS lock is off. The browser is
  the thing that knows which scheme the page arrived over, so it is the browser that asks.

## 0.63.0 - 2026-10-04

### Added
- A weekly digest. Every number this app works out sits on a page waiting to be visited, and mostly is not: devices
  nobody reviewed, signals nobody opened, a job that quietly stopped working. One message a week now carries the
  week's watching and by how many people, new devices, new signals, problems reported, where the library stands and
  anything that has failed three times running. It goes through the Apprise setup that was already there, adds no
  new data and no new analysis, and is off until switched on in Settings, Alerts and monitoring.

### Changed
- Pressing Run now on a job that waits for its hour runs it. The backup and the digest both check the clock, and
  being told a job runs at four in the morning is not an answer to being asked to run it.

### Fixed
- The backup hour's unit read "o'''clock" on the Settings page, from a shell quoting accident when it was written.

## 0.62.0 - 2026-10-04

### Added
- Access review answers a second question: which of the libraries you share with somebody have they never once
  opened. "Do they still watch" was already there, and this is the more actionable half of it. A chip lists the
  people who do use the server and have never touched something shared with them, and each of them says which.

### Changed
- History works on a phone. It was the one page that did not: nine columns in a sideways scroller with a hundred
  touch targets under 32 pixels. Below 700 pixels the same rows stack into labelled blocks, and because hiding the
  header would have taken the sorting with it, the sort moves into the bar above.
- Links and checkboxes are big enough to hit at phone width everywhere else too, which was the same twenty pixel
  target repeated down every list in the app.

## 0.61.0 - 2026-10-03

### Added
- Reports can slice the library itself. There were six sources and none of them was the thing on the disks, so the
  app could answer "watch time by user per week" and not "space by library", "files by resolution" or "how much of
  each library has never been played". A library source with seven measures (files, space used, average file,
  running time, average bitrate, never played, different shows) and a dozen dimensions, including three new ones:
  file container, release year, and whether a file has ever been played. Five presets come with it.
- Four pages carry a heading again. History, People and Map had no h1 at all, which is what a screen reader reads
  first to work out where it is.
- Live activity says when it changes. The strip at the top of the dashboard redraws itself every few seconds and
  announced nothing; there is now one polite line reporting how many streams are playing. Every error note is a
  live region too, so a failure that happens while a page is open is heard rather than appearing silently.

### Changed
- A report source with no clock no longer offers a date range. The library is a snapshot of how things are now, so
  a range would have been a control that changed nothing. If dates are set anyway the report says it covered all
  of it rather than quietly ignoring them.

## 0.60.0 - 2026-10-03

### Added
- A file with something already happening to it says so wherever it is listed. Both the poster wall and Files worth
  attention now carry a "tidying" or "being replaced" marker, so browsing for a replacement for something that is
  already downloading no longer looks like a file nobody has touched.

### Changed
- The remediation queue, and the count beside it in the Library nav, fill in the moment something is queued rather
  than on the next visit to the page. Queueing happens on one page and shows up on another, which made a file sent
  to Radarr look like it had gone nowhere.
- Asking for a replacement says what it is doing while it is doing it. The request can take a few seconds, and the
  picker used to sit there unchanged, which is how the same file gets asked for twice. The button now reads
  "Asking Radarr..." and the other releases are held until the answer comes back.

### Fixed
- Two places still sent you to "Library, Replacements" for a queued replacement. That section is called the
  remediation queue now.

## 0.59.0 - 2026-10-03

### Added
- Tidying waits for the house to go quiet. Reading and rewriting a whole film is minutes of the disks' attention
  for a file nobody is waiting on, which makes it the one piece of work here that somebody else can feel, so a
  queued job now holds until the streams stop. Queue twenty files at teatime and they are done by morning. Switch
  it off under Settings, Library and files to have them run the moment they are asked for. A job that is waiting
  stays on the queue and says why, rather than being taken off it and looking stalled

## 0.58.0 - 2026-10-03

### Added
- Ban the device and Ban the address are rule actions. A rule could stop a stream and could not stop it coming back,
  so the same device could be caught every evening for ever while the only way to end it was to go and ban it by
  hand. Both halves were first class features that could not see each other. Timed by default, because a rule acting
  on its own should not make a permanent decision quietly, and recorded as banned by a rule so the list never looks
  like somebody's choice
- A rule action's settings can offer a list of answers rather than a text box, which is what the ban length uses.
  Typing a number of hours into a text area is not a question anybody should be asked

## 0.57.0 - 2026-10-03

### Changed
- Files worth attention sends the row rather than the file. Each of the three questions behind it selects what it
  needs for its own sorting, and the answer was being passed on whole: every subtitle track, the full path, and
  every finding with its entire description, two hundred times over, so the page could print one line of it. 420 KB
  to draw 57. It is 67 KB now, and 8 KB over the wire
- A rebuild no longer reinstalls every dependency. They sit on their own layer, so changing a line of Python does
  not fetch sixty packages again. The shadowing problem that made this look impossible is handled by uninstalling
  the placeholder package, which leaves everything it pulled in behind

### Removed
- Five routes nothing called: the two library lists that Files worth attention replaced, the enforcement log the
  Log page does not read, and the sync status Settings shows under Tasks. The two library ones were tested, which
  made them look maintained; those tests now ask the services directly, which is what they were really about

## 0.56.0 - 2026-10-03

### Changed
- Two components asking for the same thing at the same moment now make one request, and a handful of answers that
  do not change while you are looking at them are remembered for a few seconds. Clicking twice round every tab:
  127 requests before, 98 after, with the users list going from twelve to two and the filter options and the
  library list from eight each to one. Live activity, the dashboard and anything about a stream are deliberately
  left out, because a stale number there is worse than a second request, and any write empties the lot

## 0.55.0 - 2026-10-03

### Added
- A sync that turns up a new device or a shared account signal says so, through Apprise. These are the two things
  this app exists to notice and the two it never mentioned: both sat on a page until somebody went and looked. Only
  ever about what that sync found, never the backlog
- And a way to clear the backlog, on People and on the signals list. An alert is worth nothing unless the normal
  state is nought, and there was no way to reach nought from twenty eight devices except by clicking twenty eight
  times, which is presumably why nobody had. A count that reads the same number for three years says nothing
- Why streams transcode now says whether any of it was done on a GPU. The app has always recorded this and never
  mentioned it, and software transcoding spends most of a processor core on each stream where the same work on an
  integrated GPU is nearly free. Said only when there are enough transcodes to mean something
- A Run the rules now button on the Rules page. The endpoint behind it has existed and been audited since rules
  were built and nothing called it, so the only way to see whether a rule did what you meant was to wait for the
  next sweep and read the Log

## 0.54.0 - 2026-10-03

### Fixed
- The dashboard held a database connection for the whole of the Tautulli round trip, once for every browser with the
  page open, out of a pool of fifteen. That is the shape that took the app down when the poster wall was added, and
  this was the last place still doing it. It waits for Tautulli first and opens a session afterwards, in the thread
  that needs it
- An answer in an unexpected shape was a blank page with no message. Eleven places guarded the outer object and
  walked straight into the inner one, and the worst of them was the sign-in screen, which had no error boundary
  above it at all. The guards go all the way through now, and the boundary wraps the whole app rather than only the
  page inside it

## 0.53.0 - 2026-10-03

### Added
- The database backs itself up. Everything the app has worked out lives in one file and nowhere else: stall causes,
  shared account signals, bans, rules, reported problems, keep decisions and every setting. Tautulli can rebuild the
  raw history and none of the rest. A snapshot is taken daily, kept beside the live file so whatever already backs
  up appdata gets it too, and the last seven are kept. Taken with VACUUM INTO while the database is in use, because
  copying a SQLite file in WAL mode can catch it mid-transaction and produce something that will not open
- Settings shows what time the server thinks it is, next to the backup hour and the rules. Every time-of-day rule
  reads the container's clock, so a TZ that is not what you meant shifts them silently and for ever, and nothing
  anywhere showed it

## 0.52.0 - 2026-10-03

### Added
- A background job that keeps failing now says so. Three failures in a row sends one message through Apprise, then
  nothing more until it works again, and one more when it does, so a job broken for a week is two messages rather
  than three hundred. This was the one thing the app could not tell anyone: a job that stops working stops the app
  having the right answer, and the only sign was a page nobody had reason to open. Switch under Settings, Syncing

### Changed
- A failed job records the reason rather than the stack. Most of these raise a sentence somebody wrote to be read,
  and four thousand characters of traceback buried it on the Tasks page. The stack goes to the log, where it belongs
- pytest-xdist is a development dependency, with the numbers in pyproject for choosing how many workers. The suite
  is 326 seconds serially and 66 at eight workers. It is deliberately not switched on by default: every test builds
  its own app and database, so a full parallel run is five gigabytes, and it makes a single file slower rather than
  faster

### Fixed
- A transcode speed below zero was recorded as fact. Plex reports it as a multiple of real time and occasionally
  reports nonsense; one session here is on record at -302.8, which went into the session's minimum and stayed there,
  making a stream that was fine look like one the server could not keep up with. Anything at or below zero, or
  absurdly above real time, is now treated as not measured

## 0.51.0 - 2026-10-03

### Fixed
- Tidying an mp4 deleted it. The result was always written as mkv, whatever went in, so a job asked only to drop
  some subtitle tracks repackaged the file and removed the original, although mp4 is a modern container the plan
  never offers to repackage. The output now keeps the file's own extension unless repackaging was one of the steps
- Nothing was told when a tidy finished, so the page went on reporting the problem that had just been fixed until
  the next library scan, up to six hours later, and a renamed file left the stored path pointing at something that
  had been deleted. The item's path and size are updated and it is marked for re-reading, which the detail pass
  does within the minute
- Looking for a library under the media roots was bounded by how many directories it examined and not by how long
  that took. The same seven thousand filesystem calls are thirty milliseconds on a local disk and several seconds
  on a mounted remote share. It now gives up after two seconds and reports the library missing, which is honest and
  is what the path box is for
- An index added to a model that already had rows was never created. `create_all` checks whether a table exists and
  skips the whole of one that does, indexes included, which had been worked around for a single index by hand. They
  are now added the same way missing columns already were, so the next one appears by itself

### Changed
- Responses are compressed. JSON takes it better than almost anything, being mostly repeated key names: the largest
  response on this server goes from 420 KB to 24 KB, and the interface bundle from 435 KB to 132 KB
- Posters are fetched as JPEG. Left to itself Tautulli hands back whatever Plex has, which is PNG, and a 200x300
  poster comes to 120 KB against 21 KB as JPEG. A page of sixty of them is seven megabytes rather than one. The
  cache file carries the format in its name, so the PNGs kept by older builds are replaced rather than served under
  the wrong content type
- The library table is indexed. Thirty thousand rows and nothing but the primary key, so every library page scanned
  the whole table to show sixty titles: 34 ms a query where an index makes it 0.8 ms. A device's, an address's and a
  title's history gain the sort column too, so finding those rows no longer leaves SQLite to build a temporary tree
  to put them in order
- SQLite is told to wait for a locked database rather than give up at once, which was the default. The enforcer
  writes every five seconds, the sync writes in batches and requests write on top of both; the transactions are all
  short, so this is about waiting out a brief overlap instead of raising it into somebody's page
- The library list reads the eighteen columns it uses rather than whole rows. It was building a full object for
  every one of thirty thousand titles, including every plot summary, to show sixty: 629 ms of query against 242 ms.
  And what each file says about itself is worked out once and kept: its title, the languages on its audio tracks,
  the store it sits on and its size per hour do not depend on who watched it, so they are not redone for thirty
  thousand files on every visit. Anything that changes a file changes the key, so a tidy, a rescan, a replacement
  or a move shows the new answer on the next page load rather than at the next scan, and renaming a store or
  changing how much of a path names one drops the whole lot. Plays and stalls are never cached, since they change
  without the file changing
- oauthlib is pinned above the version carrying PYSEC-2026-4114. It arrives through apprise rather than being used
  here, so the floor is set rather than waiting for apprise to raise its own

## 0.50.0 - 2026-10-03

### Added
- A search box in Settings. It narrows the page list and the sections on the page at once, matching the name on
  screen, the key underneath it and the words around it, so the upload capacity is found by "upload", by
  "upload_capacity_mbps", or by "warn upload" when all you remember is that it was near the alert level
- Each built-in list has its own message now: a banned device, a banned address and a blocked country are three
  different things to tell somebody. Leave the address one empty to use the device wording for both. The country
  message had never been reachable in the interface at all
- Sentences that name a page of Settings are now the way there. "Connect Seerr in Settings", "Add a MaxMind key in
  Settings", "Rules are switched off in Settings" and the rest open that page rather than leaving you to find it

## 0.49.1 - 2026-10-03

### Changed
- A release in the list is one line. The badges, Waits and Auto included, sat under the name and made every row two
  lines tall, which is half the point of a list gone. They sit beside the name now and the name gives up its end
  instead, with the whole of it on hover. Eight releases take 640 pixels rather than 940

## 0.49.0 - 2026-10-03

### Added
- The release picker opens as a list, with the cards as the other view and the choice remembered. Eighteen releases
  as cards is a wall of repeated labels; as rows it is one line each, and the thing being compared, size against
  bitrate against score, lines up in a column
- Sortable columns. Clicking a heading sorts by it, clicking the same one again turns it round. The Order menu
  drives the same thing, so the two cannot disagree

### Changed
- The sort names a field rather than a direction: Size rather than Smallest, Age rather than Newest. A column
  heading you click to reverse cannot be called Smallest, and the arrow says which way round it is

## 0.48.0 - 2026-10-03

### Added
- Ban an address from its page under People, not only from a stream card, so a household found by looking rather
  than caught in the act can be stopped where you are already standing
- A ban asks how far it should reach: this address only, its /24, or its /16, with what each one costs written
  beside it. One address catches one connection, which is enough until the household's address changes; the /24
  catches it after a reconnect at the cost of up to 255 neighbours. That trade is yours to make, so it is offered
  rather than guessed
- An address inside a banned range now says so, on both its own page and the stream card, and the Unban button
  unbans whatever is actually stopping it rather than offering to ban something that is already stopped

### Changed
- A range wider than /16 is refused, with what it would have covered. A ban stops streams without asking again, so
  the one mistake worth refusing outright is the typo that quietly stops strangers

## 0.47.0 - 2026-10-02

### Added
- Banned addresses, beside banned devices. A device ban follows one machine; an address ban follows the connection,
  which is what is wanted when a device comes back under a new identifier, or when the household rather than one box
  in it is the thing to stop. A plain address or a range typed as 203.0.113.0/24, banned from a stream card or from
  the Rules page, with its own built-in rule so the Log says which list stopped a stream

### Fixed
- A banned device could keep playing for minutes. Every rule waits out the cooldown after it acts, which is right for
  a rule that fires now and then and wrong for a ban: a stop that does not land, because the client is paused or
  buffering or simply ignored it, waited a full minute before being tried again. The built-in stops now try on every
  poll, five seconds apart by default, and only their logging waits

## 0.46.1 - 2026-10-02

### Changed
- The Remediation queue's tab counts count tidying jobs as well as replacements, so Active no longer reads 0 above
  two running jobs, and a running job gets a progress bar and the name of whoever asked for it, since a rule acting
  on its own is the case worth going to look at

### Fixed
- The tidying jobs list reported its steps in whichever shape the job was stored in, a bare list for jobs from
  before track picking and an object for ones after. It reports the step keys either way now

## 0.46.0 - 2026-10-02

### Added
- Library, Remediation queue. Tidying a file's tracks and replacing it with a better copy are the same job from
  where you are standing, so they share a page: Active shows what is being worked on, History what was. Tidying
  used to appear as a banner above Files worth attention, which is not anywhere anybody would go looking for it
- Add an AAC stereo track, as a tidying step on its own. Offered on any file that does not already have one, not
  only on files something is wrong with: a surround track is the usual reason a phone or a browser converts the
  audio, and the fix is not to throw the surround away but to put a small stereo track beside it and let each
  client take the one it wants. Downmixed from whichever track carries the fullest mix, and the originals are kept

### Fixed
- A library whose sampled file had been deleted since the scan read it was reported missing, and the miss was
  remembered, so the other files in it were never tried. The search now asks for the film's own folder rather than
  the file, since the file is the part that gets renamed, re-encoded or deleted while the folder stays, and it is
  allowed a few goes with different files before it gives up on a library
- Settings now pulls a few files per library rather than judging each one on whatever happened to be in a shared
  sample of the forty most recent, where a quiet library could be represented by a single stale path

## 0.45.1 - 2026-10-02

### Changed
- The Unraid template now defaults the media mount to /mnt/user/data/media rather than /mnt/user, and says in the
  second mount's description that a remote share under /mnt/remotes belongs there. Both host paths stay editable
  from Edit on the container; only the container side, /media and /media2, is fixed, because that is what Settings
  is told about. The README and compose file show two mounts the same way

## 0.45.0 - 2026-10-02

### Fixed
- Media roots only matched on names, which meant they found nothing when Plex's own container maps its shares to
  different names, as it usually does: a library Plex calls /movies is often /media/Films here, sharing no name with
  anything. When the names do not line up the roots are now walked instead, looking for the directory that holds the
  file itself, which has one answer and does not care what anything is called. Two levels down, so a share mounted
  whole still works. Walked once per library and remembered, hit or miss, so it never costs a walk a file

### Added
- Settings, Library and files now says what is inside each mounted directory, or that it is empty, not mounted, or
  cannot be read. A root with the wrong names in it and a root the container cannot open look identical from
  outside, and that is the one thing nobody can check without being inside the container

### Changed
- The button that rechecks the mounts saves first when there is anything to save, and says so. It used to check
  whatever the server still had and ask you to remember to save, which is a thing to forget

## 0.44.0 - 2026-10-02

### Added
- A path box that lists what the container can actually see. Click it and it shows the directories at that path,
  typing filters them, Tab completes as far as the names agree, and clicking one goes into it. Used for the media
  directories and for setting a library's path by hand, because which directories exist inside a container is a
  question only the container can answer

### Changed
- Settings has had a pass over it. Behaviour and Access, which between them held eleven unrelated sections, are now
  Syncing, Live and rules, Library and files, People and privacy, and Sign-in: one subject a page, short enough to
  read in one go. The two near-identical sections about reported problems, one on each old page, are one section
- Settings inputs now fit their values. On and off is a switch rather than a dropdown. A number is a number box with
  its unit beside it and bounds on it, instead of free text with the unit in brackets after its name. A comma
  separated list, such as the subtitle languages to keep or the trusted proxy addresses, is a list of chips you add
  to one at a time. Apprise URLs get a box that takes one per line, which is how they are pasted
- library_store_depth, which decides how much of a path names the disk a file sits on, is reachable in Settings for
  the first time, under Library and files, Storage

## 0.43.0 - 2026-10-02

### Added
- Media roots. Rather than a mount per library and a path typed in for each, give the container the directory your
  libraries sit in and the app finds each one underneath it: a library Plex calls /movies is looked for at
  /media/movies and at /media itself, and whichever answers is remembered for the rest of that library. More than
  one root, because libraries are often split across two shares or two pools

### Changed
- Settings, Behaviour, Tidying files is now a list of mounted directories you add rows to, and a table of every
  library Plex reports saying where each one was found, with a box to set by hand only the ones it could not. It
  replaces the single comma separated plex=here box, which gave no way to see what had worked
- The Unraid template asks for one media directory and an optional second, instead of six named shares. The README
  and the compose file mount one directory too

## 0.42.2 - 2026-10-02

### Added
- An Unraid container template, in unraid/cartographarr.xml. Copy it to the templates-user folder and the Docker tab
  adds Cartographarr with every path, port and variable as a field, media shares included, so mounts are edited in
  the interface rather than remembered as flags on a command

## 0.42.1 - 2026-10-02

### Added
- Settings, Behaviour, Tidying files now says whether tidying can work at all: whether ffmpeg is in the image, and
  how many of the paths Plex reports this container can actually open, naming the shares that are missing. Answered
  by trying rather than by telling somebody what to read

### Changed
- A file that cannot be reached now says which path failed and the exact mount that would fix it, rather than
  "set the path map in Settings" without saying where that is. The README shows the mounts in the run command too

## 0.42.0 - 2026-10-02

### Added
- Tidy the tracks now lists the file's own tracks: untick any subtitle or audio track to drop it, and choose which
  audio track plays first. A choice made here wins over anything worked out from Settings, because somebody is
  looking at the actual list. Seven subtitle tracks in seven languages are neither duplicates nor picture-only, so
  no rule offered to touch them before this
- All, none, and first language only, because a file with fifty six subtitle tracks is a real file and fifty six
  clicks is not an interface. A file is still never left with no sound: unticking every audio track keeps them all

## 0.41.2 - 2026-10-02

### Fixed
- The last three routes that held a database session while they waited on Tautulli, Radarr, Sonarr or Seerr now hand
  it back first: opening a history row, opening a media panel, and restoring a user in Tautulli. None of them can
  flood the pool the way a page of posters did, but it is the same mistake and it is now absent rather than rare

## 0.41.1 - 2026-10-01

### Changed
- The Library uses the width of the screen. It shared a layout with Settings, which is capped at 1180 pixels because
  prose and form fields stop being readable past about a thousand. Tables and a wall of posters want every pixel a
  wide screen has, so the Library gets its own cap and the posters a slightly larger tile

## 0.41.0 - 2026-10-01

### Fixed
- The whole app could hang while a page full of posters loaded. Each poster was proxied through Tautulli with a
  database session held open across the call, and there are fifteen connections in the pool, so a hundred posters
  starved every other page of the database. The image route holds no session now, and nor does live activity, which
  is polled by three pages at once and calls Tautulli first
- Posters are kept in the data directory after the first fetch and served from there, so a library page costs one
  fetch per item ever rather than one a visit. No more than four are fetched at once, and the wall asks for sixty
  rather than a hundred and twenty

### Added
- Tidying can answer to Settings: an audio language to put first when a file has several, subtitle languages worth
  keeping, and audio languages worth keeping. A file that would be left silent keeps everything whatever the setting
  says
- Rules can run the tidying. "Tidy the tracks" as a rule action does whatever that file needs, or the steps you name,
  under the same daily cap and record-only switch as every other rule

## 0.40.0 - 2026-10-01

### Added
- Browse: the library as a wall of posters, sorted by whatever is wrong today. Biggest per hour, highest bitrate,
  most stalls, most transcoded, most watched, least watched, or most wrong with it. Each poster carries what the app
  can prove about that file, and pressing one opens the whole card, findings, replacement and tidying included, so
  nothing has to be navigated to
- The same page switches to a list, which keeps the ticks and the bulk tagging in Radarr or Sonarr. Big for what
  they are is folded into it: it was this page with one sort and one filter

### Fixed
- Store names were read from the database once per file rather than once per page, because an empty set of names
  read as "no names yet, go and look". On a library of thirty thousand that was thirty thousand queries, and four
  seconds of every library page

## 0.39.0 - 2026-10-01

### Changed
- ffmpeg and ffprobe come from a pinned static build rather than Debian's packages. Installing them with apt pulled
  four hundred packages and took ten minutes on a home line, for about 300 MB of image; two static binaries copied
  from `mwader/static-ffmpeg:9.0.2` are a fraction of that, pull in parallel with the UI build, and sit above the
  source so an ordinary code change never recopies them

### Added
- The release picker is tiles rather than table rows: what each release would fix, what it is made of, how big, how
  fast, how old, where from, and the profile score, all at once. Filter by resolution, source, size, and whether the
  service would import it by itself or hold it for you
- Releases are ordered on two numbers rather than one blended one: how many of this file's problems a release would
  fix, then the service's own score against your profile. Blending them would mean deciding what a fixed soundtrack
  is worth in custom format points, and nothing says that

## 0.38.0 - 2026-10-01

### Added
- Big for what they are, a new Library page: every file sorted by size per hour, so a three hour film and a forty
  minute cartoon can be compared. Bitrate alone cannot do that. Narrow it by size per hour, resolution, library,
  audio language and films against episodes, and tag what is left in Radarr or Sonarr to work through later
- Tagging is capped at a hundred at a time: a filter matching two thousand files is a filter to narrow, not a
  button to press

## 0.37.0 - 2026-10-01

### Added
- Tidy the tracks, on a file card: convert styled subtitles to SRT, drop picture subtitles that already exist as
  text, drop duplicate subtitle tracks, add an AC3 track beside audio nothing can play, repackage an old container.
  ffmpeg and ffprobe now ship in the image. Nothing re-encodes the picture, so a film takes minutes rather than hours
- What it would do is worked out from what has already been read into the database, so the list shows whether or not
  the media is mounted here. The command itself is built from ffprobe's own stream list at the moment of running,
  because mapping streams needs their real indexes
- One file at a time, with progress and a Stop button at the top of Files worth attention. The result is checked
  against the original for length and for having a picture in it, and only then replaces it

### Changed
- The compose file documents the media mounts this needs. Mount the shares at the paths Plex already reports and
  there is nothing to configure; where they differ, set the path map in Settings

## 0.36.2 - 2026-09-26

### Fixed
- The meridians on the home page globe stopped at 80 degrees, leaving a bare cap where they should meet at the pole.
  They now run the whole way. Parallels still stop short, since at the pole one is a point

## 0.36.1 - 2026-09-26

### Added
- The theme editor says when the text and the page are too close to read, with the actual ratio. It is the one
  choice a colour picker can make that cannot be undone by looking, since the picker ends up on the page nobody
  can read

## 0.36.0 - 2026-09-25

### Added
- A Globe toggle on the Map tab, beside the other layers. Every layer works on it: places, heat, live streams,
  banned devices and the country shading. It is remembered, and it survives a theme change, which rebuilds the
  style underneath

## 0.35.0 - 2026-09-25

### Added
- A theme editor, under Settings, Appearance. Four colours per theme: the page, the panels and menus, the top bar
  and the text. Everything else follows a step at a time, so raised panels, borders and quieter text stay in
  agreement rather than being fourteen separate decisions. The top bar is its own colour now, and dark schemes to
  start from are offered (neutral, black, warm, Plex) for anyone who wants the blue-grey gone
- Accent stays separate and still tints on top, so a green accent on a neutral grey scheme works

### Fixed
- "Failed to fetch dynamically imported module" after an update. index.html named the last build's chunks and was
  being cached; it is now sent with no-cache while the hashed assets beside it are kept for a year. A tab left open
  across an update reloads itself once when it reaches for a chunk that has gone

## 0.34.0 - 2026-09-25

### Added
- A signal now says when one of the two networks has been putting that account in several cities anyway. A phone's
  address belongs to its carrier's nearest gateway, which can be two states away and a different one each evening,
  and that explains a signal without anybody sharing anything. Worked out from the account's own plays over six
  months, and shown rather than acted on, because whether a network wandering between four cities is a phone or a
  family is a judgement. On the library this was written against it explains 19 of the 27 remaining signals

## 0.33.0 - 2026-09-25

### Fixed
- A viewing carried from one network or device to another is no longer a shared account signal. A phone that leaves
  mobile data for the wifi at home is recorded against two addresses, and one device cannot be in two places; the
  same thing picked up on the television within half an hour of the phone leaving off is one viewing continuing.
  Two people watching the same title from two cities overlap for the length of it, not for a few minutes, and are
  still flagged
- On the library this was written against that clears 14 of 41 signals, all of them false. Open signals that no
  longer qualify are cleared on the next sweep by themselves; anything already reviewed or ignored is left alone

## 0.32.4 - 2026-09-25

### Fixed
- Stalls recorded live were never given a cause at the moment they were recorded. The code that works one out used a
  name it had not imported, inside a try that quietly logged the failure, so every stall waited for the next sync to
  be explained. Found by running the linter, which is now part of the audit script so the next one of these is caught
  the same way

## 0.32.3 - 2026-09-25

### Fixed
- The new stall cause is now understood by the two places that reason about causes rather than just listing them: a
  person whose stalls are mostly single streams that kept stalling no longer reads as "no pattern yet", and a file
  card explains what that shape means and what to compare it against

## 0.32.2 - 2026-09-25

### Fixed
- The README described the Library pages as they were before the three of them became Files worth attention, and one
  place in the app still called a lens by its old name

## 0.32.1 - 2026-09-25

### Changed
- Awkward to play opens in about a fifth of the time on a large library. It was reading the track lists of every file
  in the library on every visit, and describing twelve thousand files in order to show two hundred. It now reads the
  few columns it needs, remembers what it worked out against the moment each file was last scanned, and fills in the
  detail only for the rows on screen

## 0.32.0 - 2026-09-25

### Changed
- Awkward to play now believes what happened as well as what the tracks say. A file whose audio was converted for
  people who actually watched it is listed even when its track list looks unremarkable, which on the library this was
  written against is where most of the converting was coming from: ordinary AAC 5.1 and DTS that particular sticks
  cannot take. Files the track list already condemns are not listed twice

## 0.31.1 - 2026-09-25

### Changed
- Why streams transcode now names the devices as well as the platforms. Android tells you nothing you can act on;
  the stick in the back bedroom that accounts for a fifth of all transcoding does

## 0.31.0 - 2026-09-25

### Added
- Shared account signals now say how often the same account has been flagged between the same two places. A route
  that keeps coming back is nearly always how that connection is carried, a phone on a mobile network or a VPN with
  a favourite exit, rather than two people. Nothing is hidden: the count is shown so the ones worth reading stand
  out, and the pattern can be ignored from the signal itself as before

## 0.30.0 - 2026-09-25

### Added
- A stall cause for one stream that kept stalling. A stream that rebuffered eleven times in one sitting was being
  called eleven one-offs, which says the opposite of what happened. On the library this was written against it moves
  21 of 52 stalls out of "no pattern yet" and names them properly, and rules can ask about it like any other cause

### Fixed
- The Issues heading and its buttons no longer run off the side of a phone

## 0.29.0 - 2026-09-25

### Added
- Settings can now work out the problem bitrate from your own streams instead of leaving you with a round number.
  Every remote stream is already recorded with the file's bitrate and whether it stalled, so it offers the bitrate
  nine in ten clean remote streams stayed under, and says what that is made of. It fills the field and leaves saving
  to you, because a stall can be a bad evening on somebody else's line as easily as a file that is too big
- Nothing is offered when there is too little remote watching to say, or when the files that stalled are no bigger
  than the ones that played cleanly, which is itself worth knowing

## 0.28.0 - 2026-09-24

### Added
- Why, beside each store on Storage: what the stalling there is actually made of. Who it happened to, on what, which
  titles, and whether it was on your own network or out on the internet. A mount with a bad number is not always bad
  storage, and the breakdown is what tells a failing disk from one household on a poor line
- The warning above the table now points at that breakdown rather than straight at the storage

## 0.27.0 - 2026-09-24

### Added
- Storage now shows each store week by week, so a mount going downhill can be told from one bad evening. It counts
  the share of plays that stalled at all rather than the number of stalls, because one stream that rebuffers forty
  times is one stream that went badly, and it says which way each store is heading once there are enough weeks to say
- Weeks from before this app started watching live streams are drawn as a gap rather than as weeks where nothing went
  wrong, and the week in progress is marked as not over yet

## 0.26.0 - 2026-09-24

### Added
- Rules can now ask for a better copy. "Grab a better copy" searches and takes the best release that would fix what
  is actually wrong with the file, never one held for a manual import and never one that fixes nothing, and answers
  to the day's limit on automatic downloads in Settings. What it queues follows the same path as a replacement asked
  for by hand and shows up in the list as asked for by a rule
- Rules can answer a report: "Add a note to the report" leaves a note here and in Seerr, signed as coming from a
  rule, and "Mark the report resolved" closes it with a note saying why. Asked from a file or a replacement instead
  of a report, it closes whatever was reported about that file, which is what a replacement landing usually answers

## 0.25.1 - 2026-09-24

### Fixed
- Plays that ran past midnight were never imported. Tautulli writes a history row when the stream stops but dates it
  from when it started, so a film put on at half eleven arrives after midnight with yesterday's date on it. The sync
  asked only for rows since the newest start time it had seen, so that row fell outside the window and was never
  asked for again. The window now opens three days earlier than the watermark, and history is asked for oldest first
  so a row written while the sync is paging cannot fall through a join
- Everything already lost this way comes back on the first sync after updating, which reads all of history again

## 0.25.0 - 2026-09-24

### Added
- The globe on the home page can be taken hold of and turned. It stays where it is put for a few seconds, then
  carries on turning from there. Scrolling over it scrolls the page, and on a touch screen a finger on the
  background scrolls rather than drags, because that is what a finger on a background is for
- A moon, in orbit, with a stream playing on it. It is a joke, and it says so when you press it
- A faint glow around the planet, sitting on the edge of the sphere itself: the component measures where the
  projection actually put the sphere rather than working it out from the size of the box, which is why it lands on
  the rim at any window size
- Stars and a grid behind it all, in the theme's own ink, fading out towards the foot of the page

## 0.24.0 - 2026-09-24

### Changed
- The home page is a menu against the globe rather than a page of cards. The globe is drawn rather than fetched:
  coastlines and a grid of meridians in the accent, no labels, no roads, no cities, set off the left edge and close
  enough to be cropped by it. Where to go is a list beside it, with the two numbers worth knowing (what is playing,
  what is still open) in the corner
- The accent chosen in Settings now reaches the whole interface, not only the parts that light up. Borders, raised
  surfaces, the land on the map, the first chart series and the cool end of the heat ramp are all pulled a little way
  towards it, so a green install looks green throughout rather than grey with green buttons
- The map and the globe repaint when the accent changes, instead of waiting for a reload

## 0.23.0 - 2026-09-23

### Added
- A slowly turning globe behind the home page, painted from the same colours as everything else, so it follows the
  theme and the accent. It carries the layers from the map: where people watch from, heat, what is playing right now,
  and the country list, each on its own small toggle
- The globe stops turning when the tab is hidden or the machine asks for less motion, and is left out entirely where
  there is no WebGL

## 0.22.0 - 2026-09-23

### Changed
- Problem files, Messy files and Worth a second look are one page: Files worth attention, asked three ways. Trouble
  for viewers, awkward to play, or taking up room. Every row reads the same and offers the same things, so a file
  found for taking up room can be replaced, and one found for its audio can be kept and stop being suggested
- Find a replacement is offered on any file, not only one with something wrong, because taking up room is reason
  enough

## 0.21.0 - 2026-09-23

### Added
- Rules can be about something other than a live stream: a file behaving badly, a report somebody raised, a
  replacement finishing or stalling, or a person going quiet. Those are swept every ten minutes, through the same
  matcher, record only switch and Log as any rule
- Two actions that work on a file rather than a stream: ask Radarr or Sonarr to look for a better release, or tag it
- A daily cap per rule, and a tighter one across every rule for anything that spends bandwidth. Hitting a cap is
  recorded, because a rule that wanted to act fifty times is worth knowing about

## 0.20.0 - 2026-09-23

### Added
- Rules can see how much of the server's upload each person is using, in Mbps and as a share of capacity, and how
  much is in use altogether. A rule can then act on whoever is filling the pipe, and only when it is actually full

## 0.19.0 - 2026-09-23

### Added
- A colour of your own, under Settings, Appearance. Buttons, links, map pins and charts follow it, light and dark are
  worked out from it, and the sign-in page has it before anyone signs in

## 0.18.0 - 2026-09-23

### Added
- Library, Worth a second look: big files nobody watches, biggest first, with why each one stands out and which
  storage it is on. Nothing is deleted from here; a file you decide to keep is marked kept and stops being suggested

## 0.17.0 - 2026-09-23

### Added
- Word goes out through Apprise when somebody reports a problem, carrying what this app already knew about that file,
  so the message says "no audio most devices can play" rather than only "the sound is wrong". Switch it off under
  Settings, Alerts and monitoring
- Reported problems are a source in Reports: by kind, by title, by who reported them, open against resolved, over
  time. Two ready-made ones come with it

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
