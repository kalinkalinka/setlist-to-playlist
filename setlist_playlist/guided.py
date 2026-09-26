#!/usr/bin/env python3
"""
guided.py -- the whole job as a conversation, for people typing in a terminal.

Run `setlist-playlist` with nothing after it and this takes over: it says what
the tool does, asks for a band, shows the show it found and lets you drop
songs, asks where the playlist should go, signs you in if needed, lets you fix
any wrong recording on the spot, and builds it.

Everything here is a thin layer over the same pieces the plain command uses,
so the two can never disagree about which show or which recording is right.
Agents never see this: it only runs when a person is at a terminal.
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from . import cli, corrections, setup_wizard, signin_page, spotify, ytmusic
from .setlistfm import MissingApiKey, SetlistFmError, load_api_key, setlist_for


def _style(code: str):
    on = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    return (lambda text: f"\033[{code}m{text}\033[0m") if on else (lambda text: text)


bold, dim, green, red = _style("1"), _style("2"), _style("32"), _style("31")


def _ask(question: str, default: str = "") -> str:
    try:
        answer = input(question).strip()
    except EOFError:
        raise KeyboardInterrupt from None
    return answer or default


def _yes(question: str, default: bool = True) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    answer = _ask(f"{question} {hint} ").lower()
    return default if not answer else answer in {"y", "yes"}


def _menu(question: str, options: list[tuple[str, str, str]], default: str) -> str:
    """Numbered choices; each option is (value, label, one-line explanation)."""
    print(f"\n{bold(question)}\n")
    for number, (_, label, why) in enumerate(options, 1):
        print(f"  {number}) {label}")
        if why:
            print(f"     {dim(why)}")
    numbers = {str(n): value for n, (value, _, _) in enumerate(options, 1)}
    default_number = next(n for n, v in numbers.items() if v == default)
    while True:
        answer = _ask(f"\nChoose 1-{len(options)} [{default_number}]: ", default_number)
        if answer in numbers:
            return numbers[answer]
        print("Type one of the numbers.")


def _welcome() -> None:
    print(f"\n{bold('Setlist to Playlist')}")
    print("Turns a band's latest concert into a playlist you can play.")
    print(dim("Setlists come from setlist.fm. Press Ctrl-C at any time to stop.\n"))


def _make_sure_of_key() -> bool:
    try:
        load_api_key()
        return True
    except SetlistFmError:
        pass
    print("First, a one-time step: this needs a free setlist.fm key (about a minute).")
    if _yes("Set it up on a page in your browser? (It walks you through it.)"):
        signin_page.run(ytmusic.DEFAULT_AUTH_PATH)
    else:
        setup_wizard.ensure_api_key(interactive=True)
    try:
        load_api_key()
        return True
    except SetlistFmError:
        print(red("\nStill no setlist.fm key, so I can't look anything up yet."))
        return False


def _find_show():
    while True:
        band = _ask(bold("\nWhich band? "))
        if not band:
            continue
        print(dim("Looking it up on setlist.fm..."))
        try:
            return setlist_for(band)
        except MissingApiKey:
            raise
        except SetlistFmError as err:
            print(red(str(err)))
            print("Check the spelling, or try the band's full name.")


def _show_setlist(show, songs, notes) -> None:
    print(f"\n{bold(cli._describe_show(show))}")
    for note in notes:
        print(dim(f"  {note}"))
    print()
    for number, song in enumerate(songs, 1):
        print(f"  {number:2}. {song.title}")


def _trim(songs):
    """Let them drop songs by number before anything is searched."""
    while True:
        answer = _ask("\nPress Enter to use these songs, or type numbers to drop "
                      "(e.g. 1 7): ")
        if not answer:
            return songs
        try:
            drop = {int(part) for part in answer.replace(",", " ").split()}
        except ValueError:
            print("Type song numbers separated by spaces, or just press Enter.")
            continue
        if not drop <= set(range(1, len(songs) + 1)):
            print(f"Numbers go from 1 to {len(songs)}.")
            continue
        songs = [s for n, s in enumerate(songs, 1) if n not in drop]
        for number, song in enumerate(songs, 1):
            print(f"  {number:2}. {song.title}")


def _choose_destination() -> str:
    current = setup_wizard.load_config().get("service")
    if current:
        names = {"ytmusic": "YouTube Music", "spotify": "Spotify",
                 "file": "a file for another app"}
        if _yes(f"\nPut it on {names[current]}, like last time?"):
            return current
    choice = _menu("Where should the playlist go?", [
        ("ytmusic", "YouTube Music", "Free. You copy a login from Chrome once; it expires every few weeks."),
        ("spotify", "Spotify (Premium only)", "Spotify only allows this on paid accounts."),
        ("file", "Another app", "Apple Music, Amazon Music, Tidal, Deezer, free Spotify... via a file."),
    ], default=current or "ytmusic")
    config = setup_wizard.load_config()
    config["service"] = choice
    setup_wizard.save_config(config)
    return choice


def _args(band: str, service: str) -> argparse.Namespace:
    return cli.build_parser().parse_args([band, "--service", service])


def _to_file(show, songs) -> int:
    args = _args(show.artist, "file")
    args.yes = True
    code = cli._save_for_another_app(args, show, songs)
    if _yes("\nOpen TuneMyMusic in your browser now?"):
        webbrowser.open("https://www.tunemymusic.com")
    return code


def _fix_recordings(service, show, songs, found):
    """Offer to swap any match for a link they paste, and remember it."""
    while True:
        answer = _ask("\nAll good? Press Enter to continue, or type a song number to "
                      "fix its recording: ")
        if not answer:
            return found
        if not answer.isdigit() or not 1 <= int(answer) <= len(songs):
            print(f"Type a number from 1 to {len(songs)}, or press Enter.")
            continue
        title = songs[int(answer) - 1].title
        link = _ask(f'Paste the link to the right "{title}" (in the app: Share > Copy link): ')
        try:
            track = corrections.track_id_from(link, service.name)
        except ValueError as err:
            print(red(str(err)))
            continue
        match = service.track_details(track)
        if not match:
            print(red("Couldn't find that track. Check the link and try again."))
            continue
        corrections.remember(service.name, show.artist, title, track)
        found = [(t, match if t == title else m) for t, m in found]
        if title not in {t for t, _ in found}:
            found.append((title, match))
            order = [s.title for s in songs]
            found.sort(key=lambda pair: order.index(pair[0]))
        print(green(f'  {title}  ->  {cli._artists_of(match)} - {match.get("title")}  '
                    "(your choice; remembered for next time)"))


def run() -> int:
    try:
        _welcome()
        if not _make_sure_of_key():
            return 1
        show, songs, notes = _find_show()
        if not songs:
            print("That show has no playable songs in it.")
            return 1
        _show_setlist(show, songs, notes)
        songs = _trim(songs)
        if not songs:
            print("No songs left, so there is nothing to make.")
            return 0

        destination = _choose_destination()
        if destination == "file":
            return _to_file(show, songs)

        args = _args(show.artist, destination)
        try:
            service = cli.open_service(args)
        except (ytmusic.YouTubeMusicError, spotify.SpotifyError) as err:
            print(red(f"\n{err}"))
            print("Run  setlist-playlist setup  to sign in on a page in your browser.")
            return 1

        found, missing = cli.match_songs(service, show, songs)
        if missing:
            print("Not found: " + ", ".join(missing))
        found = _fix_recordings(service, show, songs, found)
        if not found:
            print("Nothing to add.")
            return 1

        title = cli._playlist_name(show.artist, show.iso_date)
        if not _yes(f'\nCreate the private playlist "{title}" with {len(found)} songs?'):
            print("Left it alone.")
            return 0
        try:
            url = service.create_playlist(title, f"{show.describe()}. {cli.ATTRIBUTION}",
                                          [m for _, m in found], "PRIVATE")
        except (ytmusic.YouTubeMusicError, spotify.SpotifyError) as err:
            print(red(f"\n{err}"))
            return 1
        print(green(f"\nDone: {url}"))
        print(dim(cli.ATTRIBUTION))
        if _yes("Open it now?"):
            webbrowser.open(url)
        return 0
    except KeyboardInterrupt:
        print("\nStopped. Nothing else was changed.")
        return 130

