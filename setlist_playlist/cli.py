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
import difflib
import re
import pathlib
import sys

from . import corrections, export, setup_wizard, signin_page, spotify, ytmusic
from .setlistfm import MissingApiKey, SetlistFmError, setlist_for

ATTRIBUTION = "Setlist from setlist.fm."

# Some stops are not failures. "Nobody has chosen a service" and "your login
# expired" are steps only the person can take, so they are reported as a next
# step and exit cleanly -- an agent should relay them, not announce a crash.
NEEDS_YOU = 0


NEEDS_KEY = (
    "This needs a free setlist.fm API key, once. It takes about a minute.\n"
    "The easiest way is the set-up page: run  setlist-playlist setup . It opens "
    "in their browser and walks them through it; an agent can run it for them."
)


TRANSFER_STEPS = (
    "\nTo turn it into a playlist on Spotify (free or Premium), Apple Music,\n"
    "Amazon Music, Tidal, Deezer and others, use TuneMyMusic:\n"
    "  tunemymusic.com -> Let's Start -> Upload file -> pick this CSV\n"
    "  -> choose your service and sign in -> Start Transfer.\n"
    "Check the first track if it was intro music played from tape; it may not match."
)


def _handoff(message: str) -> int:
    print(f"\nNEXT STEP FOR YOU\n{message}")
    return NEEDS_YOU


def _playlist_name(artist: str, show_date: str) -> str:
    """`<Band> <Year> Setlist`, matching how concert playlists are usually named."""
    year = show_date[:4] or str(datetime.date.today().year)
    return f"{artist} {year} Setlist"


def _describe_show(show) -> str:
    return f"{show.artist} - {show.describe()}"


def _artists_of(match: dict) -> str:
    return ", ".join(a["name"] for a in (match.get("artists") or []) if a.get("name"))


def _plain(text: str) -> str:
    """Strip everything that varies between catalogues: case, punctuation, spacing."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _looks_right(match: dict, artist: str, title: str) -> bool:
    """Is this search result actually the song we asked for, by whom we asked?

    A catalogue search always returns *something*: asking for Frozen Crown's
    "Iris" returns their song "Crown Eternal". So check both halves before
    believing it.
    """
    if not match:
        return False
    wanted_artist, wanted_title = _plain(artist), _plain(title)
    got_title = _plain(match.get("title"))

    by_them = any(
        wanted_artist in _plain(a.get("name")) or _plain(a.get("name")) in wanted_artist
        for a in (match.get("artists") or []) if a.get("name")
    )
    same_song = (
        wanted_title == got_title
        or wanted_title in got_title
        or got_title in wanted_title
        or difflib.SequenceMatcher(None, wanted_title, got_title).ratio() >= 0.8
    )
    return by_them and same_song


def _find_best(service, band: str, song) -> tuple[dict | None, str]:
    """Find a song, preferring the band's own recording.

    When a band covers something, they have often recorded it themselves --
    Angra's "Wuthering Heights" is on Angels Cry, and that is the version the
    audience heard. Only when the band has no recording of their own is the
    original artist the right answer, as with Frozen Crown playing "Iris".
    """
    own = service.find_song(band, song.title)
    if _looks_right(own, band, song.title):
        return own, ""
    if song.cover_of:
        original = service.find_song(song.cover_of, song.title)
        if original:
            return original, f"{song.cover_of} original; the band has no recording of their own"
    return own, ""


class _Service:
    """The few things the tool asks of a music service, wherever it plays."""

    def __init__(self, name: str, label: str, find_song, track_details, create_playlist):
        self.name = name
        self.label = label
        self.find_song = find_song
        self.track_details = track_details
        self.create_playlist = create_playlist


def resolve_service(args) -> str:
    """Which service to use: the flag, the remembered choice, or a question."""
    if getattr(args, "service", None):
        config = setup_wizard.load_config()
        if not config.get("service"):
            config["service"] = args.service
            setup_wizard.save_config(config)
        return args.service
    return setup_wizard.choose_service(interactive=not getattr(args, "no_prompt", False))


def open_service(args) -> _Service:
    """Sign in to whichever service was asked for, before any work happens."""
    interactive = not args.no_prompt
    if resolve_service(args) == "spotify":
        setup_wizard.ensure_spotify_client_id(interactive)
        client = spotify.Spotify(interactive=interactive)
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


def _save_for_another_app(args, show, songs) -> int:
    """The 'another app' route: a CSV in Downloads, plus how to import it."""
    for number, song in enumerate(songs, 1):
        print(f"{number:2}. {song.title}")
    name = args.title or _playlist_name(show.artist, show.iso_date)
    target = pathlib.Path.home() / "Downloads" / f"{name}.csv"
    if args.dry_run:
        print(f"\nNothing was saved. Run again without --dry-run to save {target}.")
        return 0
    written = export.write(target, show.artist, songs, show)
    print(f"\nSaved {len(songs)} songs to {written}")
    print(TRANSFER_STEPS)
    print(f"\n{ATTRIBUTION}")
    return 0


def command_build(args) -> int:
    setup_wizard.ensure_api_key(interactive=not args.no_prompt)
    try:
        show, songs, notes = setlist_for(args.artist, keep_tapes=args.keep_tapes)
    except MissingApiKey:
        return _handoff(NEEDS_KEY)
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

    try:
        chosen = resolve_service(args)
    except setup_wizard.ServiceNotChosen as err:
        return _handoff(str(err))
    if chosen == "file":
        return _save_for_another_app(args, show, songs)

    # Check the login before any searching, so an expired session costs a
    # second instead of a minute.
    try:
        service = open_service(args)
    except setup_wizard.ServiceNotChosen as err:
        return _handoff(str(err))
    except (ytmusic.LoginExpired, spotify.SpotifyError) as err:
        return _handoff(str(err))
    except ytmusic.YouTubeMusicError as err:
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

        match, why = _find_best(service, show.artist, song)
        if not match:
            missing.append(song.title)
            print(f"{number:2}. {song.title}  ->  not found")
            continue
        found.append((song.title, match))
        suffix = f"  ({why})" if why else ""
        print(f"{number:2}. {song.title}  ->  {_artists_of(match)} - {match.get('title')}{suffix}")

    print(f"\nFound {len(found)} of {len(songs)}.")

    seen: dict[str, str] = {}
    for song_title, match in found:
        track = match.get("videoId") or match.get("id")
        if track and track in seen:
            print(f'Note: "{seen[track]}" and "{song_title}" both matched the same '
                  f'recording, so it would play twice. Use --pick to choose one for each.')
        elif track:
            seen[track] = song_title

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


def command_service(args) -> int:
    """Show or change where playlists go from now on."""
    labels = {"spotify": "Spotify", "ytmusic": "YouTube Music",
              "file": "a CSV file for another app"}
    ready = dict(setup_wizard.ready_services(), file=True)

    if not args.service:
        current = setup_wizard.load_config().get("service")
        print(f"Playlists go to: {labels.get(current, 'not chosen yet')}")
        for name, label in labels.items():
            if name == "file":
                continue
            state = "signed in" if ready[name] else "not set up yet"
            print(f"  {label:<14} {state}")
        print('\nChange it with:  setlist-playlist service spotify   (or ytmusic)')
        return 0

    config = setup_wizard.load_config()
    was = config.get("service")
    config["service"] = args.service
    setup_wizard.save_config(config)

    print(f"Playlists will now go to {labels[args.service]}"
          + (f", instead of {labels[was]}." if was and was != args.service else "."))
    if not ready[args.service]:
        print(f"\nNEXT STEP FOR YOU\n{labels[args.service]} is not signed in yet. Run:\n"
              f"    setlist-playlist setup\n"
              f"(a page in the browser walks them through it), or in a terminal:\n"
              f"    setlist-playlist login --service {args.service}")
    return 0


def command_login(args) -> int:
    setup_wizard.ensure_api_key(interactive=True)
    try:
        chosen = resolve_service(args)
        if chosen == "file":
            print("Playlists go to a CSV file for another app, so there is nothing "
                  "to sign in to.")
            return 0
        if chosen == "spotify":
            setup_wizard.ensure_spotify_client_id(not getattr(args, "no_prompt", False))
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


def command_setup(args) -> int:
    """Open the set-up page and wait until the person finishes it."""
    status = signin_page.run(pathlib.Path(args.auth).expanduser(),
                             timeout_minutes=args.timeout,
                             open_browser=not args.no_browser)
    if not status["finished"]:
        return _handoff("The set-up page was not finished in time. Run "
                        "setlist-playlist setup  again to pick up where it left off.")

    # Spotify's permission screen has to come last: it opens its own page.
    if (status["service"] == "spotify" and status["spotify_client"]
            and not status["spotify"]):
        try:
            spotify.sign_in()
            status["spotify"] = True
        except spotify.SpotifyError as err:
            print(err)

    names = {"spotify": "Spotify", "ytmusic": "YouTube Music",
             "file": "a CSV file for another app (TuneMyMusic)"}
    print("\nSet-up finished.")
    print(f"  setlist.fm key   {'saved' if status['setlistfm'] else 'MISSING'}")
    print(f"  playlists go to  {names.get(status['service'], 'not chosen')}")
    if status["service"] in ("spotify", "ytmusic"):
        ok = status[status["service"]]
        print(f"  {names[status['service']]:<16} {'signed in' if ok else 'NOT signed in'}")
    if status["service"] == "file":
        print('\nFor another app, use:  setlist-playlist setlist "<band>" --save "<band>.csv"')

    missing = []
    if not status["setlistfm"]:
        missing.append("the setlist.fm key")
    if status["service"] in ("spotify", "ytmusic") and not status[status["service"]]:
        missing.append(f"signing in to {names[status['service']]}")
    if not status["service"]:
        missing.append("choosing where playlists go")
    if missing:
        return _handoff("Set-up is not complete yet: " + " and ".join(missing)
                        + " still to do. Run  setlist-playlist setup  again; it "
                        "skips what is already done.")
    return 0


def command_setlist(args) -> int:
    """Just print the setlist; touch no account at all."""
    setup_wizard.ensure_api_key(interactive=True)
    try:
        show, songs, notes = setlist_for(args.artist, keep_tapes=args.keep_tapes)
    except MissingApiKey:
        return _handoff(NEEDS_KEY)
    except SetlistFmError as err:
        print(err)
        return 1
    if getattr(args, "save", None):
        written = export.write(args.save, show.artist, songs, show)
        print(f"Wrote {len(songs)} songs to {written}")
        if str(written).lower().endswith(".csv"):
            print(TRANSFER_STEPS)
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
setlist-playlist setup             set everything up on a page in your browser
setlist-playlist login             save or refresh your login in the terminal
setlist-playlist service           show or change which service playlists go to

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
    parser.add_argument("--service", choices=["ytmusic", "spotify", "file"],
                        help="where to build the playlist (asked on first run, "
                             "then remembered)")
    parser.add_argument("--pick", action="append", metavar="'SONG=LINK'",
                        help='choose the recording for one song, e.g. '
                             '--pick "Fast as a Shark=https://music.youtube.com/watch?v=VQ-BgC58QnQ". '
                             'Remembered for next time; repeatable.')
    parser.set_defaults(func=command_build)
    return parser


def service_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setlist-playlist service",
        description="Show or change which music service playlists go to.",
    )
    parser.add_argument("service", nargs="?", choices=["ytmusic", "spotify", "file"],
                        help="leave empty to see the current choice")
    parser.set_defaults(func=command_service)
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
                             "connecting anything (import a CSV with TuneMyMusic "
                             "into free Spotify, Apple Music, Amazon Music, Tidal, "
                             "Deezer and others)")
    parser.set_defaults(func=command_setlist)
    return parser


def login_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setlist-playlist login",
        description="Save or refresh your YouTube Music login.",
    )
    _auth_argument(parser)
    parser.add_argument("--service", choices=["ytmusic", "spotify"],
                        help="which service to sign in to (asked if not yet chosen)")
    parser.set_defaults(func=command_login)
    return parser


def setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setlist-playlist setup",
        description="Set everything up on a page in your browser: the setlist.fm "
                    "key, where playlists go, and signing in.",
    )
    _auth_argument(parser)
    parser.add_argument("--timeout", type=int, default=30,
                        help="minutes to wait for the page to be finished (default 30)")
    parser.add_argument("--no-browser", action="store_true",
                        help="print the page address instead of opening it")
    parser.set_defaults(func=command_setup)
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
    elif argv and argv[0] == "setup":
        parser = setup_parser()
        argv = argv[1:]
    elif argv and argv[0] == "service":
        parser = service_parser()
        argv = argv[1:]
    elif argv and argv[0] == "build":
        parser = build_parser()
        argv = argv[1:]
    else:
        parser = build_parser()

    if not argv and parser.prog not in ("setlist-playlist login",
                                        "setlist-playlist service",
                                        "setlist-playlist setup"):
        print(USAGE)
        return 2

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
