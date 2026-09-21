#!/usr/bin/env python3
"""
export.py -- write the setlist to a file, for people who don't want to connect
an account at all.

A CSV is the useful format here: the playlist-transfer services people already
use (Soundiiz, TuneMyMusic and the like) take a CSV of artist and title, which
is how this reaches Apple Music, Tidal, Deezer and anything else without the
tool needing to speak to each of them.

A .txt file is written as plain "Artist - Title" lines instead, which is easier
to paste into a message or a note.
"""

from __future__ import annotations

import csv
import pathlib


def write(path: str | pathlib.Path, artist: str, songs, show=None) -> pathlib.Path:
    """Write the setlist to a .csv or .txt file and return where it landed."""
    path = pathlib.Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.suffix.lower() == ".txt":
        lines = [f"{song.cover_of or artist} - {song.title}" for song in songs]
        header = f"# {show.artist} - {show.describe()}\n# Setlist from setlist.fm: {show.url}\n" if show else ""
        path.write_text(header + "\n".join(lines) + "\n")
        return path

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["#", "Artist", "Title", "Encore", "Cover of"])
        for number, song in enumerate(songs, 1):
            writer.writerow([
                number,
                song.cover_of or artist,
                song.title,
                "yes" if song.encore else "",
                song.cover_of or "",
            ])
    return path
