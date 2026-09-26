#!/usr/bin/env python3
"""
ytmusic.py -- build a YouTube Music playlist, and handle the login.

YouTube Music has no official way for a program to act on your account, so this
borrows the login from your own browser: you copy one request out of Chrome's
developer tools and the tool saves the headers locally. That copied login is a
session, so it expires -- every few weeks, or whenever you sign out.

That expiry is normal, not a failure, so this module treats it as a step in the
conversation rather than an error: it checks the login before doing any work,
walks you through refreshing it when it has lapsed, and then carries on with
what you originally asked for.

Your login is written to a file on your own machine. It is never printed and
never sent anywhere except YouTube.
"""

from __future__ import annotations

import pathlib
import random
import re
import shutil
import subprocess
import sys
import time

DEFAULT_AUTH_PATH = pathlib.Path.home() / ".config" / "setlist-to-playlist" / "browser.json"

COPY_STEPS = """\
To let this tool use your YouTube Music account, copy one request from your
browser. It takes about a minute:

  1. Open  music.youtube.com  in Chrome, signed in to the account you want.
  2. Open developer tools:  Cmd-Option-I  (Mac)  /  Ctrl-Shift-I  (Windows, Linux)
  3. Click the  Network  tab, then reload the page (Cmd-R / Ctrl-R).
  4. In the Network tab's filter box, type:  browse
     The list may look empty at first. Scroll down in it until you see
     rows named "browse". If none appear, reload the page again.
  5. Right-click any row named "browse"  ->  Copy  ->  Copy as cURL
     (plain "Copy as cURL", not the fetch or PowerShell version)

What you copy contains your YouTube login. It is saved to a file on this
computer only. It is never displayed and never sent anywhere but YouTube.
"""


class YouTubeMusicError(RuntimeError):
    """Something went wrong with YouTube Music."""


class LoginExpired(YouTubeMusicError):
    """The saved browser login is no longer valid."""


def _require_ytmusicapi():
    try:
        import ytmusicapi  # noqa: F401
    except ImportError as err:
        raise YouTubeMusicError(
            "The ytmusicapi package is missing. Install it with:\n"
            "    pip install ytmusicapi"
        ) from err
    return sys.modules["ytmusicapi"]


def read_clipboard() -> str | None:
    """Return the clipboard contents, if we can read them on this system."""
    for command in (["pbpaste"], ["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"]):
        if shutil.which(command[0]):
            try:
                done = subprocess.run(command, capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                continue
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout
    return None


def headers_from_curl(curl: str) -> str:
    """Pull the request headers out of a "Copy as cURL" command.

    Chrome no longer offers a plain "copy request headers", but the cURL command
    carries the same headers, including the login cookie.
    """
    headers = re.findall(r"-H \$?'((?:[^'\\]|\\.)*)'", curl)
    headers += re.findall(r'-H \$?"((?:[^"\\]|\\.)*)"', curl)

    # Some versions pass the cookie with -b/--cookie instead of a -H.
    if not any(h.lower().startswith("cookie:") for h in headers):
        match = re.search(r"(?:-b|--cookie) \$?'((?:[^'\\]|\\.)*)'", curl)
        if match:
            headers.append("cookie: " + match.group(1))

    if not any(h.lower().startswith("cookie:") for h in headers):
        raise YouTubeMusicError(
            "That copied text has no login in it.\n\n"
            "Make sure you are signed in to music.youtube.com, and that you "
            'right-clicked a row named "browse" and chose Copy as cURL.'
        )
    return "\n".join(headers)


def save_login(curl_text: str, auth_path: pathlib.Path = DEFAULT_AUTH_PATH) -> pathlib.Path:
    """Turn a copied cURL command into a saved login file."""
    ytmusicapi = _require_ytmusicapi()
    headers = headers_from_curl(curl_text)
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    ytmusicapi.setup(filepath=str(auth_path), headers_raw=headers)
    auth_path.chmod(0o600)
    return auth_path


def guided_login(auth_path: pathlib.Path = DEFAULT_AUTH_PATH, reason: str | None = None):
    """Walk the person through copying their login, then save it.

    Reads the copied command straight from the clipboard where possible, so
    nothing has to be pasted into the terminal.
    """
    if not sys.stdin.isatty():
        # An agent or script is running us. Only the person can sign in, so
        # this is a next step for them, not a failure.
        raise LoginExpired(
            "YouTube Music is not signed in on this computer (or the login "
            "expired, which is normal every few weeks).\n"
            "The easiest way: run  setlist-playlist setup . A page opens in "
            "their browser and walks them through copying a login from Chrome; "
            "an agent can run it for them. In a terminal, "
            "setlist-playlist login --service ytmusic  works too.\n"
            "Then run this command again."
        )

    if reason:
        print(f"\n{reason}\n")
    print(COPY_STEPS)

    clipboard_works = read_clipboard() is not None
    if clipboard_works:
        print("  6. Come back here and press Enter. Do NOT paste it into the terminal:\n"
              "     I read it from your clipboard myself.\n")
        input("Copied it? Press Enter and I'll read it from your clipboard. ")
        curl_text = read_clipboard() or ""
    else:
        print("Paste it here, then press Ctrl-D:\n")
        curl_text = sys.stdin.read()

    if not curl_text.strip():
        raise YouTubeMusicError("Nothing was copied. Try the steps again.")

    path = save_login(curl_text, auth_path)
    print(f"\nSaved. Your login lives in {path} and nowhere else.\n")
    return path


def connect(auth_path: pathlib.Path = DEFAULT_AUTH_PATH, interactive: bool = True):
    """Return a YouTube Music session that is known to work.

    Checks the saved login before any real work happens, so an expired session
    costs one second rather than a minute of searching. If it has expired, and
    we are in a terminal, offers to refresh it right away.
    """
    ytmusicapi = _require_ytmusicapi()
    auth_path = pathlib.Path(auth_path).expanduser()

    if not auth_path.exists():
        if not interactive:
            raise LoginExpired(f"No saved YouTube Music login at {auth_path}.")
        guided_login(auth_path, reason="First time here: I need access to your YouTube Music account.")

    for attempt in (1, 2):
        try:
            session = ytmusicapi.YTMusic(str(auth_path))
            session.get_library_playlists(limit=1)  # cheap call that needs a valid login
            return session
        except Exception as err:  # noqa: BLE001 - the library raises several types
            if attempt == 2 or not interactive:
                raise LoginExpired(
                    "Your YouTube Music login has expired. Refresh it with:\n"
                    "    setlist-playlist login"
                ) from err
            guided_login(
                auth_path,
                reason="Your YouTube Music login has expired. This happens every "
                "few weeks; here is how to refresh it.",
            )

    raise LoginExpired("Could not sign in to YouTube Music.")


def _artists_of(item: dict) -> str:
    return ", ".join(a["name"] for a in (item.get("artists") or []) if a.get("name"))


def find_song(session, artist: str, title: str, pace: float = 1.0) -> dict | None:
    """Find the studio recording of one song.

    Searching with the "songs" filter returns catalogue tracks rather than
    whatever live clip or reaction video happens to rank well.
    """
    query = f"{artist} {title}".strip()
    try:
        results = session.search(query, filter="songs")
    except Exception:  # noqa: BLE001
        return None
    if pace:
        time.sleep(pace + random.uniform(0, 0.4))
    return results[0] if results else None


def track_details(session, track_id: str) -> dict | None:
    """Look up one track by id, for recordings you chose yourself."""
    try:
        details = session.get_song(track_id)["videoDetails"]
    except Exception:  # noqa: BLE001
        return None
    return {
        "videoId": track_id,
        "title": details.get("title", track_id),
        "artists": [{"name": details.get("author", "")}],
    }


def create_playlist(session, title: str, description: str, track_ids: list[str],
                    privacy: str = "PRIVATE") -> str:
    """Create a playlist and return its address."""
    playlist_id = session.create_playlist(title, description or title, privacy_status=privacy)
    if not isinstance(playlist_id, str):
        raise YouTubeMusicError(f"YouTube Music refused to create the playlist: {playlist_id!r}")
    if track_ids:
        session.add_playlist_items(playlist_id, track_ids, duplicates=True)
    return f"https://music.youtube.com/playlist?list={playlist_id}"
