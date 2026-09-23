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

## First time: ask where their playlists should go

You have no terminal, so the tool cannot ask them itself. If a run stops with
"No music service has been chosen yet", that is not an error — it is the tool
handing you a question to put to the person:

> Where would you like your playlists?
> - **Spotify** — you approve it once in your browser and it keeps working.
>   Needs a two-minute, one-time registration first.
> - **YouTube Music** — quicker to start, but you copy a login out of Chrome
>   and redo it every few weeks.

Then re-run with `--service spotify` or `--service ytmusic`. The choice is
remembered, so this happens once.

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

To hand them a file instead — a CSV imports into Apple Music, Tidal and others
through a transfer service:

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

## Things you cannot do for them

**Credentials are theirs.** Never read, print, copy or edit these files, and
never ask the person to paste their contents into the conversation:
- `~/.config/setlist-to-playlist/key` (setlist.fm)
- `~/.config/setlist-to-playlist/browser.json` (YouTube Music)
- `~/.config/setlist-to-playlist/spotify.json` (Spotify)

**Signing in needs them at the keyboard.** The command asks for a setlist.fm
key on first use, and for a YouTube Music login it needs a request copied out
of their browser's developer tools. You cannot do either. When a run reports a
missing or expired login, tell them plainly what happened and ask them to run
this themselves in their terminal:

```bash
setlist-playlist login
```

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
