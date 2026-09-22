#!/usr/bin/env python3
"""
corrections.py -- remember which recording you actually wanted.

Searching a music catalogue by title is a guess, and sometimes it guesses
wrong. Accept's 50th anniversary re-recordings of "Fast as a Shark" and
"Demon's Night" -- both with guest singers -- rank above the 1982 originals,
so a plain search picks those.

You fix it once by naming the recording you want, and the choice is saved: the
next time that band's setlist includes that song, your choice is used instead
of searching.

Corrections live in ~/.config/setlist-to-playlist/corrections.json, which is a
plain file you can read, edit, or delete.
"""

from __future__ import annotations

import json
import pathlib
import re

def corrections_path() -> pathlib.Path:
    """Worked out fresh each time, so tests and a moved home both behave."""
    return pathlib.Path.home() / ".config" / "setlist-to-playlist" / "corrections.json"


def _key(service: str, artist: str, title: str) -> str:
    """One correction per service, band and song, ignoring case and spacing."""
    tidy = lambda text: re.sub(r"\s+", " ", text.strip().lower())  # noqa: E731
    return f"{service}|{tidy(artist)}|{tidy(title)}"


def track_id_from(text: str, service: str = "ytmusic") -> str:
    """Accept either a share link or a bare id, and return the id.

    YouTube Music: https://music.youtube.com/watch?v=VQ-BgC58QnQ
    Spotify:       https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT
    """
    text = text.strip()
    if service == "spotify":
        match = re.search(r"(?:track[/:])([A-Za-z0-9]{22})", text)
        if match:
            return match.group(1)
        if re.fullmatch(r"[A-Za-z0-9]{22}", text):
            return text
        raise ValueError(f"That does not look like a Spotify track: {text!r}")

    match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    raise ValueError(f"That does not look like a YouTube Music track: {text!r}")


def load(path: pathlib.Path | None = None) -> dict[str, str]:
    path = path or corrections_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save(corrections: dict[str, str], path: pathlib.Path | None = None) -> None:
    path = path or corrections_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(corrections, indent=2, sort_keys=True) + "\n")


def remember(service: str, artist: str, title: str, track: str,
             path: pathlib.Path | None = None) -> str:
    """Save "for this band's song, use this recording" and return the track id."""
    track_id = track_id_from(track, service)
    corrections = load(path)
    corrections[_key(service, artist, title)] = track_id
    save(corrections, path)
    return track_id


def forget(service: str, artist: str, title: str,
           path: pathlib.Path | None = None) -> bool:
    corrections = load(path)
    if corrections.pop(_key(service, artist, title), None) is None:
        return False
    save(corrections, path)
    return True


def lookup(service: str, artist: str, title: str,
           path: pathlib.Path | None = None) -> str | None:
    return load(path).get(_key(service, artist, title))


def parse_pick(text: str) -> tuple[str, str]:
    """Split a --pick value: 'Fast as a Shark=VQ-BgC58QnQ'."""
    if "=" not in text:
        raise ValueError(
            'A --pick looks like  --pick "Song Title=<link or id>"  '
            f"(got {text!r})"
        )
    title, track = text.split("=", 1)
    if not title.strip() or not track.strip():
        raise ValueError(f"Both a song title and a track are needed (got {text!r})")
    return title.strip(), track.strip()
