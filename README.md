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

## Use it from an agent (Claude Code, and others)

This is designed to be handed to an agent, so you can just ask for what you
want instead of remembering commands:

> "make me a playlist of Accept's latest setlist"

Install the tool, then drop the skill file where your agent looks for skills:

```bash
pip install setlist-to-playlist

# Claude Code
mkdir -p ~/.claude/skills/setlist-playlist
curl -sL https://raw.githubusercontent.com/kalinkalinka/setlist-to-playlist/main/SKILL.md \
  -o ~/.claude/skills/setlist-playlist/SKILL.md
```

[`SKILL.md`](SKILL.md) tells the agent when this is the right tool, which
commands to run, to show you the matches before creating anything, and — the
part agents get wrong — that your logins are yours: it must never read them,
and signing in is something only you can do.

For an agent without a skills folder, `SKILL.md` is still the instructions:
point it at the file, or paste it in.

## Install it for yourself

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

**An account** — only if you want playlists built. Either works; pick one.

### Spotify (recommended)

Spotify has an official way to let a program act on your account: you approve it
once in the browser and it keeps working. Nothing to re-copy, nothing that
quietly expires.

The one-off cost is registering the tool with Spotify, which takes two minutes:
create an app at https://developer.spotify.com/dashboard, set its redirect URI
to `http://127.0.0.1:8723/callback`, copy the Client ID, and save it:

```bash
echo 'YOUR-CLIENT-ID' > ~/.config/setlist-to-playlist/spotify_client_id
setlist-playlist login --service spotify
```

(There's also a client secret. This tool doesn't need it. Leave it alone.)

Then add `--service spotify` to any command.

### YouTube Music

Run `setlist-playlist login` and it walks you through it, or just run a build
and it'll offer when it needs one.

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
setlist-playlist "Accept"                        # build it (asks before creating)
setlist-playlist "Accept" --dry-run              # show the matches, create nothing
setlist-playlist "Accept" --service spotify      # build it on Spotify instead
setlist-playlist setlist "Accept"                # just print the setlist, no account
setlist-playlist setlist "Accept" --save set.csv # write it to a file, connect nothing
setlist-playlist login                           # save or refresh your login
```

### When it picks the wrong recording

Searching by title is a guess, and re-recordings can outrank originals. Accept's
50th anniversary versions of "Fast as a Shark" and "Demon's Night", both with
guest singers, come up before the 1982 originals.

Name the one you want, and it sticks:

```bash
setlist-playlist "Accept" --pick "Fast as a Shark=https://music.youtube.com/watch?v=VQ-BgC58QnQ"
```

Paste the track's share link (or its id). The choice is saved per band and song
in `~/.config/setlist-to-playlist/corrections.json` — a plain file you can edit
or delete — and used automatically from then on.

### Without connecting anything

```bash
setlist-playlist setlist "Accept" --save accept.csv
```

A CSV imports into Apple Music, Tidal, Deezer and the rest through a transfer
service like Soundiiz or TuneMyMusic. Use a `.txt` name instead and you get
plain `Artist - Title` lines.

Other useful flags: `--keep-tapes` to keep intro music, `--title` to name the
playlist yourself, `--privacy UNLISTED|PUBLIC` (private by default), `--yes` to
skip the confirmation.

## Credits and limits

Setlist data comes from **[setlist.fm](https://www.setlist.fm/)**, whose API is
free for non-commercial use. If you build something commercial on it, talk to
them first.

YouTube Music support uses [ytmusicapi](https://github.com/sigma67/ytmusicapi),
which is unofficial. It has been reliable for years, but it isn't a supported
Google interface and could break.

MIT licensed.
