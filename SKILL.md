---
name: setlist-playlist
description: Build a playlist from a band's most recent concert setlist. Use when someone asks for a setlist as a playlist, what a band played live recently, "make me a playlist of X's latest show", "what's on X's current tour setlist", or wants a concert setlist on Spotify, YouTube Music, Apple Music or another music app.
---

# Setlist to playlist

Turn a band's most recent real concert into a playlist the person can play.

This skill drives the `setlist-playlist` command. Do not fetch setlists by
browsing setlist.fm and do not build playlists by hand — the command already
handles the parts that are easy to get wrong (skipping incomplete and festival
setlists, splitting medleys, dropping solos and walk-on music, finding covers
under the original artist).

## Who you are talking to

Assume the person has never opened a terminal. You run every command; they
never type one. They see only this conversation and, once, a set-up page in
their browser. Speak in their terms — "your music app", "the show in Las Vegas
on May 21" — never in flags, file paths or exit codes.

Stick to what they asked. Do not pull in other things you happen to know about
them (tickets, trips, plans) to explain why they might want this playlist.

## The conversation

Walk through these stages in order. Keep each message short; one question at
a time.

**1. First time only — say what this is.** One or two sentences: "I'll look up
the most recent full concert <band> played, using setlist.fm, and turn it into
a playlist in your music app." If the command is not installed, install it
(see *Installing*) without asking — it is part of the request.

**2. Find the show.** Run `setlist-playlist setlist "<band>"` and tell them:
the date, city and venue it chose; that it skips festival slots and incomplete
lists (only if its notes say it skipped any); and the songs, numbered. Credit
setlist.fm. If the band name matches nothing, or matches a different band, say
so and ask which they meant — never guess.

This needs no account. If it hands back a **NEXT STEP** about the setlist.fm
key, go to stage 3 first, then come back.

**3. Set up, once.** If anything is missing — the setlist.fm key, a chosen
music app, or a login — ask where their playlists should go, in plain words:

> "Which app do you listen to music on? And if it's Spotify, do you pay for
> Premium?"

Their answer decides the route:

| They use | Route |
|---|---|
| YouTube Music | connect it on the set-up page |
| Spotify **with** Premium | connect it on the set-up page |
| Spotify without Premium, Apple Music, Amazon Music, Tidal, Deezer, anything else | no connecting — you make a file and walk them through TuneMyMusic (stage 5b) |

Then run the set-up page for them (see *Setting up*) and tell them what to
expect in one sentence: "A page just opened in your browser — follow it and
press Finish at the end; I'll wait." Do not explain every step in chat; the
page does that.

**4. Preview.** Run `setlist-playlist "<band>" --dry-run` and show the matches.
Say plainly how many were found ("15 of 15"), any song not found, and anything
the tool warned about (two songs matching the same recording). Ask: "Shall I
make the playlist?"

**5a. Build it** (YouTube Music or Spotify). Run
`setlist-playlist "<band>" --yes` and give them the link. Mention it is private
— only they can see it — unless they asked otherwise.

**5b. Or hand them a file** (every other app). Run
`setlist-playlist setlist "<band>" --save "<Band> <Year> Setlist.csv"` into a
folder they can find (Downloads), then guide them:

1. Go to tunemymusic.com and click **Let's Start**.
2. Choose **Upload file** and pick the file (the Artist and Title columns, if asked).
3. Choose your app and sign in there, as you normally would.
4. Check the matches, then click **Start Transfer**.

If the setlist opens with music played from tape, warn that the first song may
not match and can simply be removed.

**6. Close.** Ask whether any song sounds wrong. If one does, see *When a song
matches the wrong recording*.

## When the tool hands something back to the person

Output beginning **`NEXT STEP FOR YOU`** is not a failure. The command exits
cleanly. It means the next move belongs to the person, because only they can
sign in or choose. Never call it an error, a crash, or a failed command.

- **Nobody has chosen a music app yet** → stage 3.
- **A key or login is missing or expired** → run the set-up page again. YouTube
  Music logins expire every few weeks; say that this is normal, then carry on
  where you left off.

While you wait, you already have the setlist — show it rather than leaving them
with nothing.

## Setting up

Run this yourself, in the background, and wait for it to finish:

```bash
setlist-playlist setup
```

It opens a page in their browser that walks them through each step (setlist.fm
key, where playlists go, signing in), checks each answer really works, and
saves it on their computer. It waits until they press Finish (up to 30
minutes), then prints what is now in place. If it ends with **NEXT STEP FOR
YOU**, something was skipped; tell them what, and run it again when they are
ready — it skips what is already done.

Never ask them to paste a key or login into the chat. The page is where it goes.

If no browser opens (a remote machine), run it with `--no-browser` and give
them the address it prints. People who prefer the terminal can use
`setlist-playlist login` instead.

## Installing

```bash
setlist-playlist --help
```

If that fails, install it and tell them in one line that you did:

```bash
python3 -m pip install --user git+https://github.com/kalinkalinka/setlist-to-playlist
```

On a Mac with Homebrew's Python you may need `--break-system-packages`. If the
command is still not found afterwards, run it as `python3 -m setlist_playlist.cli`.

## When a song matches the wrong recording

Re-recordings and anniversary versions with guest singers often outrank the
original. The tool also warns when two songs matched the same recording, which
means the playlist would play it twice — tell the person when that happens.

Covers are handled for them: the band's own recording is preferred, and the
original artist is used only when the band never recorded it. The output says
which happened.

If the person says a track is wrong, ask them to open the right version in
their music app, choose Share → Copy link, and send you the link. Then run:

```bash
setlist-playlist "<band>" --pick "<Song Title>=<link>" --dry-run
```

The choice is saved, so it applies on every later run without being repeated.

## Changing music app later

When someone says they want to switch — "use Spotify from now on", "put these
on YouTube Music instead" — change the saved default:

```bash
setlist-playlist service spotify     # or ytmusic
```

`setlist-playlist service` shows where playlists go now and what is signed in.
Playlists already made stay where they are. If the new app is not signed in,
run the set-up page.

## Things you cannot do for them

**Credentials are theirs.** Never read, print, copy, move or edit these files,
and never ask the person to paste their contents into the conversation:
- `~/.config/setlist-to-playlist/key` (setlist.fm)
- `~/.config/setlist-to-playlist/browser.json` (YouTube Music)
- `~/.config/setlist-to-playlist/spotify.json` (Spotify)

**Signing in needs them, not you.** The setlist.fm key, the YouTube Music login
and the Spotify registration can only be done by the person, on the set-up page.

**Spotify needs Premium.** Spotify only lets programs build playlists for
Premium accounts. For free Spotify, use the file route. Do not look for a
workaround.

## Rules

- Preview with `--dry-run` and show the matches before creating a playlist.
- Keep playlists private unless the person asks otherwise.
- Report honestly: the show it picked, songs that were dropped, songs not
  found. Do not present a 14-song playlist as if it were the full 18-song set.
- If the band name does not match, ask; never guess.
- Setlist data comes from setlist.fm. Credit it when you show a setlist.
