---
name: setlist-playlist
description: Build a playlist from a band's most recent concert setlist. Use when someone asks for a setlist as a playlist, what a band played live recently, "make me a playlist of X's latest show", "what's on X's current tour setlist", or wants a concert setlist on Spotify or YouTube Music.
---

# Setlist to playlist

Turn a band's most recent real concert into a playlist on the person's own
Spotify or YouTube Music account.

This skill drives the `setlist-playlist` command. Do not fetch setlists by
browsing setlist.fm and do not build playlists by hand — the command already
handles the parts that are easy to get wrong (skipping incomplete and festival
setlists, splitting medleys, dropping solos and walk-on music, finding covers
under the original artist).

## Check it is installed

```bash
setlist-playlist --help
```

If that fails, install it and tell the person what you did:

```bash
pip install git+https://github.com/kalinkalinka/setlist-to-playlist
```

## When the tool hands something back to the person

Output beginning **`NEXT STEP FOR YOU`** is not a failure. The command exits
cleanly. It means the next move belongs to the person, because only they can
sign in. Relay it as a next step, in their own terms. Never call it an error,
a crash, or a failed command.

There are two of these.

**Nobody has chosen a service yet.** The message says which services are
already signed in on this machine and which need setting up — pass that on,
because it decides the answer. If one is ready to use and the other needs a
two-minute registration, say so plainly rather than presenting a bare choice.
Then re-run with `--service spotify` or `--service ytmusic`. It is remembered,
so this happens once.

**A key or login is missing or expired.** YouTube Music logins expire every few
weeks; this is routine. Run the set-up page for them (see *Setting up*) and
carry on where you left off. Do not ask for their password, cookie or key, and
do not try to sign in for them.

While you wait for either, you already have the setlist — show it to them
rather than leaving them with nothing.

## The normal job

**Always preview first.** Show the person what was found before creating
anything.

```bash
setlist-playlist "<band name>" --dry-run
```

Report to them:
- which show it chose, with the date and city
- the notes it printed, which say what it dropped and why
- any song it could not find

Then, if they are happy, build it:

```bash
setlist-playlist "<band name>" --yes
```

Give them the playlist link it prints. The playlist is private by default.

## Just the setlist, no account

When someone only wants to know what a band played, or does not want to
connect an account:

```bash
setlist-playlist setlist "<band name>"
```

To hand them a file instead — this is also the route when they use free
Spotify (the Spotify login needs Premium; on a free account the Web API box is
greyed out), Apple Music, Amazon Music, Tidal, Deezer, or anything else
TuneMyMusic supports. Suggest TuneMyMusic: Let's Start → Upload file → the CSV →
their service → Start Transfer. Warn that a taped intro may not match:

```bash
setlist-playlist setlist "<band name>" --save "<name>.csv"
```

## When a song matches the wrong recording

Re-recordings and anniversary versions with guest singers often outrank the
original. The tool also warns when two songs matched the same recording, which
means the playlist would play it twice — tell the person when that happens.

Covers are handled for them: the band's own recording is preferred, and the
original artist is used only when the band never recorded it. The output says
which happened.

If the person says a track is wrong, ask them for the correct recording's
share link and run:

```bash
setlist-playlist "<band>" --pick "<Song Title>=<link>" --dry-run
```

The choice is saved, so it applies on every later run without being repeated.

## Changing service later

When someone says they want to switch — "use Spotify from now on", "put these
on YouTube Music instead" — change the saved default rather than passing a flag
each time:

```bash
setlist-playlist service spotify     # or ytmusic
```

To check where playlists currently go, and what is signed in:

```bash
setlist-playlist service
```

Playlists already made stay where they are; this only affects new ones. If the
new service is not signed in, the output says so as a next step for them.

## Things you cannot do for them

**Credentials are theirs.** Never read, print, copy or edit these files, and
never ask the person to paste their contents into the conversation:
- `~/.config/setlist-to-playlist/key` (setlist.fm)
- `~/.config/setlist-to-playlist/browser.json` (YouTube Music)
- `~/.config/setlist-to-playlist/spotify.json` (Spotify)

**Signing in needs them, not you.** The setlist.fm key, the YouTube Music login
and the Spotify registration can only be done by the person. You cannot do them.

## Setting up

Many people using this have never opened a terminal. Do not ask them to type
commands. Run this yourself, in the background:

```bash
setlist-playlist setup
```

It opens a page in their browser that walks them through each step (setlist.fm
key, where playlists go, signing in), checks each answer really works, and
saves it on their computer. Tell them in one sentence what to expect: "A page
just opened in your browser — follow it, and press Finish at the end." The
command waits until they press Finish (up to 30 minutes), then prints what is
now in place. If it ends with **NEXT STEP FOR YOU**, something was skipped; run
it again when they are ready — it skips what is already done.

Never ask them to paste a key or login into the chat. The page is where it goes.

If no browser opens (a remote machine), run it with `--no-browser` and give
them the address it prints. People who prefer the terminal can use
`setlist-playlist login` instead.

YouTube Music logins expire every few weeks. This is normal, not a fault —
say so, rather than reporting it as an error.

## Rules

- Preview with `--dry-run` and show the matches before creating a playlist.
- Keep playlists private unless the person asks otherwise.
- Report honestly: the show it picked, songs that were dropped, songs not
  found. Do not present a 14-song playlist as if it were the full 18-song set.
- If the person names a band that does not exist on setlist.fm, say so and ask
  whether they meant a similarly named one, rather than guessing.
- Setlist data comes from setlist.fm. Credit it when you show a setlist.
