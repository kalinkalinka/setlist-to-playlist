#!/usr/bin/env python3
"""
setlistfm.py -- look up a band's most recent real setlist on setlist.fm.

Give it a band name; it gives you back an ordered list of songs, cleaned up so
it can be turned into a playlist.

Two things make this harder than "fetch the newest show":

1. The newest entry is often not usable. It may be tonight's concert, added
   before the band has played a note, or a half-remembered list someone typed
   from memory. setlist.fm marks these, and we skip them.

2. A festival slot is not a representative setlist. A band that plays 18 songs
   on its own tour plays 9 at a festival. If you asked for "the setlist", you
   almost certainly meant the real show. We compare each show against the
   band's own recent average and skip the unusually short ones.

Data comes from setlist.fm. An API key is required -- see the README.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

API_ROOT = "https://api.setlist.fm/rest/1.0/"

# setlist.fm rejects bare "name/version" user agents with a 403, so send a
# descriptive one.
USER_AGENT = "setlist-to-playlist/0.1 (+https://github.com/kalinkalinka/setlist-to-playlist)"

# Names that are not songs: solo spots and drum breaks announced as set items.
_NOT_A_SONG = re.compile(
    r"^(drum|guitar|bass|keyboard|piano|violin|vocal)s?\s*solo$|^solo$|^jam$",
    re.IGNORECASE,
)


class SetlistFmError(RuntimeError):
    """Something went wrong talking to setlist.fm."""


def load_api_key(explicit: str | None = None) -> str:
    """Find the setlist.fm API key.

    Looked for in this order: the value passed in, the SETLISTFM_API_KEY
    environment variable, then a `.setlistfm_key` file in the current directory
    or in ~/.config/setlist-to-playlist/.
    """
    if explicit:
        return explicit.strip()
    env = os.environ.get("SETLISTFM_API_KEY")
    if env and env.strip():
        return env.strip()
    for candidate in (
        pathlib.Path(".setlistfm_key"),
        pathlib.Path.home() / ".config" / "setlist-to-playlist" / "key",
    ):
        if candidate.is_file():
            value = candidate.read_text().strip()
            if value:
                return value
    raise SetlistFmError(
        "No setlist.fm API key found.\n\n"
        "Get one (free, for non-commercial use) at:\n"
        "    https://www.setlist.fm/settings/api\n\n"
        "Then save it with:\n"
        "    echo 'YOUR-KEY' > .setlistfm_key\n"
        "or set the SETLISTFM_API_KEY environment variable."
    )


@dataclass
class Song:
    """One song as performed."""

    title: str
    tape: bool = False          # played from tape, not performed live
    cover_of: str | None = None  # original artist, if setlist.fm marks it a cover
    guest: str | None = None     # guest performer on this song
    encore: bool = False

    def __str__(self) -> str:
        return self.title


@dataclass
class Show:
    """One concert."""

    date: str          # as printed by setlist.fm, dd-mm-yyyy
    artist: str
    venue: str
    city: str
    country: str
    tour: str | None
    url: str
    songs: list[Song] = field(default_factory=list)
    info: str | None = None

    @property
    def incomplete(self) -> bool:
        return bool(self.info and "incomplete" in self.info.lower())

    @property
    def iso_date(self) -> str:
        day, month, year = self.date.split("-")
        return f"{year}-{month}-{day}"

    def describe(self) -> str:
        where = ", ".join(p for p in (self.venue, self.city, self.country) if p)
        tour = f" [{self.tour}]" if self.tour else ""
        return f"{self.iso_date} - {where}{tour}"


class SetlistFm:
    """A small read-only client for the setlist.fm API."""

    # setlist.fm allows roughly two requests a second. Stay under it.
    min_seconds_between_requests = 0.6

    def __init__(self, api_key: str | None = None, timeout: int = 20):
        self.api_key = load_api_key(api_key)
        self.timeout = timeout
        self._last_request_at = 0.0

    def _get(self, path: str, **params) -> dict:
        url = API_ROOT + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url,
            headers={
                "x-api-key": self.api_key,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )

        # Up to three tries, backing off if we are asked to slow down.
        for attempt in range(3):
            gap = time.monotonic() - self._last_request_at
            if gap < self.min_seconds_between_requests:
                time.sleep(self.min_seconds_between_requests - gap)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as err:
                if err.code == 429 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                if err.code == 404:
                    raise SetlistFmError("setlist.fm has nothing for that.") from err
                if err.code in (401, 403):
                    raise SetlistFmError(
                        "setlist.fm rejected the API key (HTTP %d). Check that the key "
                        "is correct and still active." % err.code
                    ) from err
                if err.code == 429:
                    raise SetlistFmError(
                        "setlist.fm is rate-limiting us (HTTP 429). Wait a minute "
                        "and try again."
                    ) from err
                raise SetlistFmError(f"setlist.fm returned HTTP {err.code}.") from err
            except urllib.error.URLError as err:
                raise SetlistFmError(f"Could not reach setlist.fm: {err.reason}") from err
            finally:
                self._last_request_at = time.monotonic()

        raise SetlistFmError("setlist.fm did not respond after three tries.")

    def find_artist(self, name: str) -> dict:
        """Find the artist whose name best matches what the user typed."""
        data = self._get("search/artists", artistName=name, sort="relevance")
        artists = data.get("artist", [])
        if not artists:
            raise SetlistFmError(f'No artist on setlist.fm matches "{name}".')

        wanted = name.strip().lower()
        exact = [a for a in artists if a.get("name", "").lower() == wanted]
        return (exact or artists)[0]

    def recent_shows(self, mbid: str, pages: int = 2) -> list[Show]:
        """Recent concerts by this artist, newest first."""
        shows: list[Show] = []
        for page in range(1, pages + 1):
            data = self._get(f"artist/{mbid}/setlists", p=page)
            for raw in data.get("setlist", []):
                shows.append(_parse_show(raw))
            if len(shows) >= data.get("total", 0):
                break
        return shows


def _parse_show(raw: dict) -> Show:
    venue = raw.get("venue", {}) or {}
    city = venue.get("city", {}) or {}
    show = Show(
        date=raw.get("eventDate", ""),
        artist=(raw.get("artist") or {}).get("name", ""),
        venue=venue.get("name", ""),
        city=city.get("name", ""),
        country=(city.get("country") or {}).get("name", ""),
        tour=(raw.get("tour") or {}).get("name"),
        url=raw.get("url", ""),
        info=raw.get("info"),
    )
    for one_set in (raw.get("sets", {}) or {}).get("set", []):
        is_encore = bool(one_set.get("encore"))
        for song in one_set.get("song", []):
            name = (song.get("name") or "").strip()
            if not name:
                continue
            show.songs.append(
                Song(
                    title=name,
                    tape=bool(song.get("tape")),
                    cover_of=(song.get("cover") or {}).get("name"),
                    guest=(song.get("with") or {}).get("name"),
                    encore=is_encore,
                )
            )
    return show


def choose_show(shows: list[Show], min_fraction: float = 0.8) -> tuple[Show, list[str]]:
    """Pick the most recent show that actually represents what the band plays.

    Returns the chosen show plus a plain-language note for every show we
    skipped along the way, so the caller can explain the choice.
    """
    notes: list[str] = []
    usable = [s for s in shows if s.songs and not s.incomplete]
    if not usable:
        raise SetlistFmError(
            "No complete setlist found for this artist in their recent shows."
        )

    # How long is a normal show for this band right now?
    typical = statistics.median(len(s.songs) for s in usable[:15])
    threshold = max(1, int(typical * min_fraction))

    for show in shows:
        if not show.songs:
            notes.append(f"{show.iso_date}: skipped, no songs listed yet")
            continue
        if show.incomplete:
            notes.append(f"{show.iso_date}: skipped, marked incomplete on setlist.fm")
            continue
        if len(show.songs) < threshold:
            notes.append(
                f"{show.iso_date}: skipped, only {len(show.songs)} songs "
                f"(a normal show is about {int(typical)}) - probably a festival slot"
            )
            continue
        return show, notes

    # Nothing cleared the bar; fall back to the newest complete show.
    return usable[0], notes


def clean_songs(songs: list[Song], keep_tapes: bool = False) -> tuple[list[Song], list[str]]:
    """Turn a performed setlist into a list of songs you can actually play.

    Splits medleys into their separate songs, drops solo spots, and drops
    anything played from tape (an intro recording) unless asked to keep it.
    Returns the cleaned songs plus a note for everything removed.
    """
    cleaned: list[Song] = []
    notes: list[str] = []

    for song in songs:
        # Songs played from tape need judgement. Some are the band's own music
        # -- Judas Priest open "Electric Eye" with the taped "The Hellion", and
        # it belongs in the playlist. Others are just walk-on music by someone
        # else (Judas Priest walk on to Black Sabbath's "War Pigs"), or a
        # nameless intro, and neither belongs. setlist.fm marks other people's
        # songs as covers, which tells the two apart.
        if song.tape and not keep_tapes:
            borrowed = song.cover_of is not None
            is_intro = re.search(r"\b(intro|outro)\b", song.title, re.IGNORECASE)
            if borrowed or is_intro:
                why = f"{song.cover_of} song" if borrowed else "intro music"
                notes.append(f'dropped "{song.title}" (tape, {why})')
                continue
            notes.append(f'kept "{song.title}" (tape, but the band\'s own song)')

        # setlist.fm writes a medley as one entry: "One / Two / Three"
        parts = [p.strip() for p in song.title.split(" / ") if p.strip()]
        if len(parts) > 1:
            notes.append(f'split medley "{song.title}" into {len(parts)} songs')

        for part in parts:
            if _NOT_A_SONG.match(part):
                notes.append(f'dropped "{part}" (not a song)')
                continue
            cleaned.append(
                Song(
                    title=part,
                    tape=song.tape,
                    cover_of=song.cover_of if len(parts) == 1 else None,
                    guest=song.guest,
                    encore=song.encore,
                )
            )

    return cleaned, notes


def setlist_for(artist_name: str, api_key: str | None = None, keep_tapes: bool = False):
    """The whole lookup: band name in, chosen show and cleaned songs out."""
    client = SetlistFm(api_key)
    artist = client.find_artist(artist_name)
    shows = client.recent_shows(artist["mbid"])
    show, skipped = choose_show(shows)
    songs, cleaning = clean_songs(show.songs, keep_tapes=keep_tapes)
    return show, songs, skipped + cleaning


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Find a band's most recent real setlist on setlist.fm."
    )
    parser.add_argument("artist", help='band name, e.g. "Judas Priest"')
    parser.add_argument(
        "--keep-tapes",
        action="store_true",
        help="keep intro music played from tape (dropped by default)",
    )
    parser.add_argument("--quiet", action="store_true", help="print only the song titles")
    args = parser.parse_args(argv)

    try:
        show, songs, notes = setlist_for(args.artist, keep_tapes=args.keep_tapes)
    except SetlistFmError as err:
        print(str(err))
        return 1

    if args.quiet:
        for song in songs:
            print(song.title)
        return 0

    print(f"{show.artist} - {show.describe()}")
    print(f"source: {show.url}")
    print()
    for number, song in enumerate(songs, 1):
        extras = []
        if song.cover_of:
            extras.append(f"{song.cover_of} cover")
        if song.encore:
            extras.append("encore")
        suffix = f"  ({', '.join(extras)})" if extras else ""
        print(f"{number:2}. {song.title}{suffix}")
    if notes:
        print("\nnotes:")
        for note in notes:
            print(f"  - {note}")
    print("\nSetlist data from setlist.fm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
