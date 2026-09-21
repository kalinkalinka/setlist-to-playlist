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

from . import ytmusic
from .setlistfm import SetlistFmError, setlist_for

ATTRIBUTION = "Setlist from setlist.fm."


def _playlist_name(artist: str, show_date: str) -> str:
    """`<Band> <Year> Setlist`, matching how concert playlists are usually named."""
    year = show_date[:4] or str(datetime.date.today().year)
    return f"{artist} {year} Setlist"


def _describe_show(show) -> str:
    return f"{show.artist} - {show.describe()}"


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
    session = None
    if not args.dry_run:
        try:
            session = ytmusic.connect(args.auth, interactive=not args.no_prompt)
        except ytmusic.YouTubeMusicError as err:
            print(err)
            return 1
    else:
        try:
            session = ytmusic.connect(args.auth, interactive=not args.no_prompt)
        except ytmusic.YouTubeMusicError:
            # A preview does not need an account; searching works signed out.
            import ytmusicapi

            session = ytmusicapi.YTMusic()

    print(f"Looking up {len(songs)} songs on YouTube Music...\n")
    found: list[tuple[str, dict]] = []
    missing: list[str] = []
    for number, song in enumerate(songs, 1):
        # A cover the band never recorded will not be in their catalogue, so
        # search under whoever originally released it.
        search_artist = song.cover_of or show.artist
        match = ytmusic.find_song(session, search_artist, song.title, pace=args.pace)
        if not match:
            missing.append(song.title)
            print(f"{number:2}. {song.title}  ->  not found")
            continue
        found.append((song.title, match))
        print(f"{number:2}. {song.title}  ->  {ytmusic._artists_of(match)} - {match.get('title')}")

    print(f"\nFound {len(found)} of {len(songs)}.")
    if missing:
        print("Not found: " + ", ".join(missing))

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
        url = ytmusic.create_playlist(
            session, title, description,
            [m["videoId"] for _, m in found if m.get("videoId")],
            privacy=args.privacy,
        )
    except ytmusic.YouTubeMusicError as err:
        print(err)
        return 1

    print(f"\nDone: {url}")
    return 0


def command_login(args) -> int:
    try:
        ytmusic.guided_login(pathlib.Path(args.auth).expanduser())
    except ytmusic.YouTubeMusicError as err:
        print(err)
        return 1
    print("You are signed in. Run setlist-playlist \"<band>\" whenever you like.")
    return 0


def command_setlist(args) -> int:
    """Just print the setlist; touch no account at all."""
    try:
        show, songs, notes = setlist_for(args.artist, keep_tapes=args.keep_tapes)
    except SetlistFmError as err:
        print(err)
        return 1
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
    parser.set_defaults(func=command_setlist)
    return parser


def login_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setlist-playlist login",
        description="Save or refresh your YouTube Music login.",
    )
    _auth_argument(parser)
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
