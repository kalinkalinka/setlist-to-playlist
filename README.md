# setlist-to-playlist

Type a band's name. Get their latest concert as a playlist you can actually play.

```
$ setlist-playlist "Judas Priest"

Judas Priest - 2026-09-18 - Vorst Nationaal, Belgium [Faithkeepers Tour]

  note: dropped "War Pigs" (tape, Black Sabbath song)
  note: kept "The Hellion" (tape, but the band's own song)

Looking up 18 songs on YouTube Music...
 1. You've Got Another Thing Comin'  ->  Judas Priest - You've Got Another Thing Comin'
 2. Metal Gods                       ->  Judas Priest - Metal Gods
 ...

Create the private playlist "Judas Priest 2026 Setlist" with these 18 songs? [Y/n]
```

## Why this isn't just "fetch the newest setlist"

The newest entry on setlist.fm is often the wrong one, and a plain copy of it
makes a playlist that doesn't work. This tool applies the judgements you'd make
yourself if you were doing it by hand:

**It skips shows that aren't really there.** Tonight's concert gets a page before
the band has played a note. Other entries are half-remembered and flagged as
incomplete. Both are skipped.

**It skips festival slots.** A band that plays 18 songs on its own tour plays 9 at
a festival. If you asked for "the setlist", you meant the real show, so shows far
shorter than that band's own recent average are passed over.

**It splits medleys.** `Demon's Night / Starlight / Losers and Winners` is three
songs, and you want all three.

**It drops things that aren't songs.** Drum solos, guitar solos, and the walk-on
music: Judas Priest walk on to Black Sabbath's "War Pigs", which shouldn't be in
a Judas Priest playlist.

**But it keeps taped songs the band actually wrote.** Judas Priest play "The
Hellion" from tape as the intro to "Electric Eye" — that one belongs. The
difference is knowable: walk-on music is somebody else's song.

**It finds covers under the original artist.** When a band plays something they
never recorded, searching their own catalogue finds nothing, so it looks for
whoever released it.

Every one of these decisions is printed as a note, so you can see what it did and
disagree.

## Install

```bash
pip install setlist-to-playlist
```

## Setup

**A setlist.fm API key** — free, and takes a minute.

1. Get one at https://www.setlist.fm/settings/api
2. Save it:

```bash
mkdir -p ~/.config/setlist-to-playlist
echo 'YOUR-KEY' > ~/.config/setlist-to-playlist/key
```

Or set `SETLISTFM_API_KEY` in your environment.

**A YouTube Music login** — only if you want playlists built. Run
`setlist-playlist login` and it walks you through it, or just run a build and
it'll offer when it needs one.

YouTube Music has no official way to let a program act on your account, so this
borrows the login from your browser: you copy one request out of Chrome's
developer tools, and the tool saves those headers to
`~/.config/setlist-to-playlist/browser.json`.

That's a session, so **it expires** — every few weeks, or whenever you sign out
of YouTube. This is normal. The tool checks your login before it searches for
anything, so an expired session costs you a second rather than a minute, and
when it has lapsed it shows you the steps, reads the new copy from your
clipboard, and finishes the job you asked for.

Your login is kept in a file on your own machine, readable only by you. It is
never printed and never sent anywhere except YouTube.

## Use

```bash
setlist-playlist "Accept"                  # build it (asks before creating)
setlist-playlist "Accept" --dry-run        # show the matches, create nothing
setlist-playlist setlist "Accept"          # just print the setlist, no account
setlist-playlist login                     # save or refresh your login
```

Useful flags: `--keep-tapes` to keep intro music, `--title` to name the playlist
yourself, `--privacy UNLISTED|PUBLIC` (private by default), `--yes` to skip the
confirmation.

## Credits and limits

Setlist data comes from **[setlist.fm](https://www.setlist.fm/)**, whose API is
free for non-commercial use. If you build something commercial on it, talk to
them first.

YouTube Music support uses [ytmusicapi](https://github.com/sigma67/ytmusicapi),
which is unofficial. It has been reliable for years, but it isn't a supported
Google interface and could break.

MIT licensed.
