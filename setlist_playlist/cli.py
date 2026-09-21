#!/usr/bin/env python3
"""
setlist-playlist -- turn a band's latest concert into a playlist you can play.

    setlist-playlist "Judas Priest"

Looks up their most recent real setlist on setlist.fm, finds each song on
YouTube Music, and builds a private playlist in that order.

Nothing is created until you have seen the songs it found: the first run always
shows you the matches and asks before it builds anything.
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import sys

from . import corrections, export, spotify, ytmusic
from .setlistfm import SetlistFmError, setlist_for

ATTRIBUTION = "Setlist from setlist.fm."


def _playlist_name(artist: str, show_date: str) -> str:
    """`<Band> <Year> Setlist`, matching how concert playlists are usually named."""
    year = show_date[:4] or str(datetime.date.today().year)
    return f"{artist} {year} Setlist"


def _describe_show(show) -> str:
    return f"{show.artist} - {show.describe()}"


def _artists_of(match: dict) -> str:
    return ", ".join(a["name"] for a in (match.get("artists") or []) if a.get("name"))


class _Service:
    """The few things the tool asks of a music service, wherever it plays."""

    def __init__(self, name: str, label: str, find_song, track_details, create_playlist):
        self.name = name
        self.label = label
        self.find_song = find_song
        self.track_details = track_details
        self.create_playlist = create_playlist


def open_service(args) -> _Service:
    """Sign in to whichever service was asked for, before any work happens."""
    if args.service == "spotify":
        client = spotify.Spotify(interactive=not args.no_prompt)
        return _Service(
            "spotify", "Spotify",
            client.find_song,
            client.track_details,
            lambda title, description, matches, privacy: client.create_playlist(
                title, description, [m["uri"] for m in matches],
                public=(privacy == "PUBLIC"),
            ),
        )

    try:
        session = ytmusic.connect(args.auth, interactive=not args.no_prompt)
    except ytmusic.YouTubeMusicError:
        if not args.dry_run:
            raise
        # A preview needs no account; searching works signed out.
        import ytmusicapi

        session = ytmusicapi.YTMusic()

    return _Service(
        "ytmusic", "YouTube Music",
        lambda artist, title: ytmusic.find_song(session, artist, title, pace=args.pace),
        lambda track_id: ytmusic.track_details(session, track_id),
        lambda title, description, matches, privacy: ytmusic.create_playlist(
            session, title, description,
            [m["videoId"] for m in matches if m.get("videoId")], privacy=privacy,
        ),
    )


def command_build(args) -> int:
    try:
        show, songs, notes = setlist_for(args.artist, keep_tapes=args.keep_tapes)
    except SetlistFmError as err:
        print(err)
        return 1

    if not songs:
        print("That show has no playable songs in it.")
        return 1

    print(f"\n{_describe_show(show)}")
    print(f"setlist.fm: {show.url}\n")
    for note in notes:
        print(f"  note: {note}")
    if notes:
        print()

    # Check the login before any searching, so an expired session costs a
    # second instead of a minute.
    try:
        service = open_service(args)
    except (ytmusic.YouTubeMusicError, spotify.SpotifyError) as err:
        print(err)
        return 1

    # Recordings you have chosen yourself, this run or previously.
    try:
        for pick in args.pick or []:
            title_to_fix, track = corrections.parse_pick(pick)
            corrections.remember(service.name, show.artist, title_to_fix, track)
            print(f'Using your chosen recording for "{title_to_fix}".')
    except ValueError as err:
        print(err)
        return 1

    print(f"\nLooking up {len(songs)} songs on {service.label}...\n")
    found: list[tuple[str, dict]] = []
    missing: list[str] = []
    for number, song in enumerate(songs, 1):
        chosen = corrections.lookup(service.name, show.artist, song.title)
        if chosen:
            match = service.track_details(chosen)
            if match:
                found.append((song.title, match))
                print(f"{number:2}. {song.title}  ->  {_artists_of(match)} - "
                      f"{match.get('title')}  (your choice)")
                continue
            print(f"{number:2}. {song.title}  ->  your chosen recording is gone; searching instead")

        # A cover the band never recorded will not be in their catalogue, so
        # search under whoever originally released it.
        search_artist = song.cover_of or show.artist
        match = service.find_song(search_artist, song.title)
        if not match:
            missing.append(song.title)
            print(f"{number:2}. {song.title}  ->  not found")
            continue
        found.append((song.title, match))
        print(f"{number:2}. {song.title}  ->  {_artists_of(match)} - {match.get('title')}")

    print(f"\nFound {len(found)} of {len(songs)}.")
    if missing:
        print("Not found: " + ", ".join(missing))
    if found:
        print('\nWrong recording? Fix it and it stays fixed:\n'
              '  setlist-playlist "%s" --pick "Song Title=<paste the track link>"' % args.artist)

    title = args.title or _playlist_name(show.artist, show.iso_date)
    description = args.description or f"{show.describe()}. {ATTRIBUTION}"

    if args.dry_run:
        print(f'\nNothing was created. Run again without --dry-run to build "{title}".')
        return 0

    if not found:
        print("\nNothing to add.")
        return 1

    if not args.yes and sys.stdin.isatty():
        answer = input(f'\nCreate the private playlist "{title}" with these {len(found)} songs? [Y/n] ')
        if answer.strip().lower() in {"n", "no"}:
            print("Left it alone.")
            return 0

    try:
        url = service.create_playlist(title, description, [m for _, m in found], args.privacy)
    except (ytmusic.YouTubeMusicError, spotify.SpotifyError) as err:
        print(err)
        return 1

    print(f"\nDone: {url}")
    return 0


def command_login(args) -> int:
    try:
        if args.service == "spotify":
            spotify.sign_in()
            who = spotify.Spotify().me()
            print(f"Signed in to Spotify as {who.get('display_name') or who.get('id')}.")
        else:
            ytmusic.guided_login(pathlib.Path(args.auth).expanduser())
    except (ytmusic.YouTubeMusicError, spotify.SpotifyError) as err:
        print(err)
        return 1
    print('You are signed in. Run setlist-playlist "<band>" whenever you like.')
    return 0


def command_setlist(args) -> int:
    """Just print the setlist; touch no account at all."""
    try:
        show, songs, notes = setlist_for(args.artist, keep_tapes=args.keep_tapes)
    except SetlistFmError as err:
        print(err)
        return 1
    if getattr(args, "save", None):
        written = export.write(args.save, show.artist, songs, show)
        print(f"Wrote {len(songs)} songs to {written}")
        print(f"\n{ATTRIBUTION}")
        return 0

    print(_describe_show(show))
    print(f"setlist.fm: {show.url}\n")
    for number, song in enumerate(songs, 1):
        print(f"{number:2}. {song.title}")
    if notes and not args.quiet:
        print("\nnotes:")
        for note in notes:
            print(f"  - {note}")
    print(f"\n{ATTRIBUTION}")
    return 0


USAGE = """\
setlist-playlist "<band>"          build a playlist from their latest setlist
setlist-playlist setlist "<band>"  just print the setlist; no account needed
setlist-playlist login             save or refresh your YouTube Music login

Add --service spotify to any of these to use Spotify instead.
"""


def _auth_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--auth",
        default=str(ytmusic.DEFAULT_AUTH_PATH),
        help="where your YouTube Music login is kept",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setlist-playlist",
        description="Turn a band's latest concert setlist into a playlist.",
        epilog=USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("artist", help='band name, e.g. "Judas Priest"')
    _auth_argument(parser)
    parser.add_argument("--dry-run", action="store_true", help="show the matches, create nothing")
    parser.add_argument("--yes", "-y", action="store_true", help="do not ask before creating")
    parser.add_argument("--no-prompt", action="store_true",
                        help="never ask for a login; fail instead (for scripts)")
    parser.add_argument("--keep-tapes", action="store_true",
                        help="keep intro music played from tape")
    parser.add_argument("--title", help="playlist name (default: <Band> <Year> Setlist)")
    parser.add_argument("--description", help="playlist description")
    parser.add_argument("--privacy", default="PRIVATE",
                        choices=["PRIVATE", "UNLISTED", "PUBLIC"], help="default: PRIVATE")
    parser.add_argument("--pace", type=float, default=1.0,
                        help="seconds between searches (default 1.0)")
    parser.add_argument("--service", default="ytmusic", choices=["ytmusic", "spotify"],
                        help="where to build the playlist (default: ytmusic)")
    parser.add_argument("--pick", action="append", metavar="'SONG=LINK'",
                        help='choose the recording for one song, e.g. '
                             '--pick "Fast as a Shark=https://music.youtube.com/watch?v=VQ-BgC58QnQ". '
                             'Remembered for next time; repeatable.')
    parser.set_defaults(func=command_build)
    return parser


def setlist_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setlist-playlist setlist",
        description="Print a band's latest setlist. Touches no account.",
    )
    parser.add_argument("artist", help='band name, e.g. "Judas Priest"')
    parser.add_argument("--keep-tapes", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="song titles only")
    parser.add_argument("--save", metavar="FILE",
                        help="write the setlist to a .csv or .txt file instead of "
                             "connecting anything (a CSV imports into Apple Music, "
                             "Tidal and others through a transfer service)")
    parser.set_defaults(func=command_setlist)
    return parser


def login_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setlist-playlist login",
        description="Save or refresh your YouTube Music login.",
    )
    _auth_argument(parser)
    parser.add_argument("--service", default="ytmusic", choices=["ytmusic", "spotify"],
                        help="which service to sign in to (default: ytmusic)")
    parser.set_defaults(func=command_login)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # "login" and "setlist" are commands; anything else is a band name, so
    # `setlist-playlist "Judas Priest"` works without a verb.
    if argv and argv[0] == "login":
        parser = login_parser()
        argv = argv[1:]
    elif argv and argv[0] == "setlist":
        parser = setlist_parser()
        argv = argv[1:]
    elif argv and argv[0] == "build":
        parser = build_parser()
        argv = argv[1:]
    else:
        parser = build_parser()

    if not argv and parser.prog != "setlist-playlist login":
        print(USAGE)
        return 2

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
