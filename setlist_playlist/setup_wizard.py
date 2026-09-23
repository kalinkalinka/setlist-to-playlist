#!/usr/bin/env python3
"""
setup_wizard.py -- the first run, done as a conversation.

Nobody should have to read a README to use this. The first time you run it,
with nothing set up, it asks the two questions that matter -- where do you want
your playlists, and what is your setlist.fm key -- takes the answers by paste,
and then gets on with the thing you actually asked for.

Your answers are remembered, so it only ever asks once.
"""

from __future__ import annotations

import json
import pathlib
import sys
import webbrowser

def config_dir() -> pathlib.Path:
    """Worked out fresh each time, so tests and a moved home both behave."""
    return pathlib.Path.home() / ".config" / "setlist-to-playlist"


def config_path() -> pathlib.Path:
    return config_dir() / "config.json"


def key_path() -> pathlib.Path:
    return config_dir() / "key"

SETLISTFM_SIGNUP = "https://www.setlist.fm/settings/api"


class ServiceNotChosen(RuntimeError):
    """Nobody has said where playlists should go, and we cannot ask from here."""


def load_config(path: pathlib.Path | None = None) -> dict:
    path = path or config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(config: dict, path: pathlib.Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")


def _ask(question: str, default: str = "") -> str:
    try:
        answer = input(question).strip()
    except EOFError:
        return default
    return answer or default


def _offer_to_open(url: str) -> None:
    if _ask(f"Open {url} in your browser? [Y/n] ", "y").lower() not in {"n", "no"}:
        webbrowser.open(url)


def ensure_api_key(interactive: bool = True) -> str | None:
    """Make sure we have a setlist.fm key, asking for one if we may."""
    from .setlistfm import SetlistFmError, load_api_key

    try:
        return load_api_key()
    except SetlistFmError:
        pass

    if not interactive or not sys.stdin.isatty():
        return None

    print(
        "\nFirst, this needs a setlist.fm API key. It's free, it's yours, and it\n"
        "takes about a minute: sign in, fill in the short form, and they show you\n"
        "the key straight away.\n"
    )
    _offer_to_open(SETLISTFM_SIGNUP)
    key = _ask("\nPaste your setlist.fm API key here (or press Enter to skip): ")
    if not key:
        return None

    target = key_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(key + "\n")
    target.chmod(0o600)
    print(f"Saved to {target}\n")
    return key


def choose_service(interactive: bool = True, path: pathlib.Path | None = None) -> str:
    """Ask where playlists should go, once, and remember the answer."""
    path = path or config_path()
    config = load_config(path)
    if config.get("service"):
        return config["service"]

    if not interactive or not sys.stdin.isatty():
        # An agent is running us, or a script is. Do not pick on someone's
        # behalf: say what is needed so the question reaches a person.
        raise ServiceNotChosen(
            "No music service has been chosen yet.\n\n"
            "Ask which they want, then run again with one of:\n"
            "    --service spotify     sign in once in a browser; keeps working\n"
            "    --service ytmusic     copy a login out of Chrome; expires every few weeks\n\n"
            "The choice is remembered after that."
        )

    print(
        "\nWhere would you like your playlists?\n"
        "\n"
        "  1) Spotify         Sign in once in your browser. Keeps working.\n"
        "                     Needs a two-minute, one-time registration first.\n"
        "\n"
        "  2) YouTube Music   Copy a login out of Chrome's developer tools.\n"
        "                     Quicker to start, but expires every few weeks.\n"
    )
    answer = _ask("Choose 1 or 2 [1]: ", "1")
    service = "spotify" if answer.startswith("1") else "ytmusic"

    config["service"] = service
    save_config(config, path)
    print(f"\nUsing {'Spotify' if service == 'spotify' else 'YouTube Music'}. "
          "You can change this later with --service.\n")
    return service


def ensure_spotify_client_id(interactive: bool = True) -> str | None:
    """Walk someone through registering the app, and take the id by paste."""
    from .spotify import CLIENT_ID_PATH, SETUP_STEPS, SpotifyError, load_client_id  # noqa: F401

    try:
        return load_client_id()
    except SpotifyError:
        pass

    if not interactive or not sys.stdin.isatty():
        return None

    print("\n" + SETUP_STEPS.split("Then save the Client ID:")[0])
    _offer_to_open("https://developer.spotify.com/dashboard")
    client_id = _ask("\nPaste your Client ID here (or press Enter to skip): ")
    if not client_id:
        return None

    CLIENT_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLIENT_ID_PATH.write_text(client_id + "\n")
    CLIENT_ID_PATH.chmod(0o600)
    print(f"Saved to {CLIENT_ID_PATH}\n")
    return client_id
