#!/usr/bin/env python3
"""
build_ytmusic_playlist.py — create a YouTube Music playlist from a song list.

Companion to the setlist-identification pipeline: once you have a setlist (from
setlist.fm or the fingerprint/transcription pipeline), this turns it into a YT
Music playlist in seconds instead of clicking through the web UI song by song.

Uses `ytmusicapi` (unofficial YouTube Music library). It searches the YT Music
catalog with the "songs" filter, so it picks the actual studio song — not a random
video/live version — and preserves your setlist order.

--------------------------------------------------------------------------------
ONE-TIME SETUP
--------------------------------------------------------------------------------
1. Install:            pip install ytmusicapi
2. Authenticate:       ytmusicapi browser
     - Open music.youtube.com (logged in) in your browser.
     - Open DevTools -> Network, click any request to music.youtube.com,
       copy the *request headers*, and paste when prompted.
     - This writes `browser.json` (your session credentials).
   KEEP browser.json LOCAL AND PRIVATE. Never commit it (see .gitignore).

--------------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------------
  # song list: one song title per line (blank lines and #comments ignored)
  python3 build_ytmusic_playlist.py \
      --auth browser.json \
      --artist "Scorpions" \
      --title  "Scorpions 2026 Setlist" \
      --desc   "60th Anniversary Tour" \
      --songs  scorpions.txt \
      --dry-run          # preview matches first; drop this flag to actually build

Each line in --songs is combined with --artist into the search query
("Scorpions" + "Coming Home"). Omit --artist if your lines already include it.

Order in the playlist = order in the file.
"""

import argparse
import random
import sys
import time


def load_songs(path):
    songs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                songs.append(s)
    return songs


def artists_str(item):
    return ", ".join(a["name"] for a in (item.get("artists") or []) if a.get("name"))


def main():
    ap = argparse.ArgumentParser(description="Build a YouTube Music playlist from a song list.")
    ap.add_argument("--songs", required=True, help="text file, one song per line")
    ap.add_argument("--title", required=True, help="playlist title")
    ap.add_argument("--artist", default="", help="artist name prepended to each search")
    ap.add_argument("--desc", default="", help="playlist description")
    ap.add_argument("--auth", default="browser.json", help="ytmusicapi auth file (default browser.json)")
    ap.add_argument("--privacy", default="PRIVATE", choices=["PRIVATE", "UNLISTED", "PUBLIC"])
    ap.add_argument("--filter", default="songs", help="search filter (songs|videos); default songs")
    ap.add_argument("--pace", type=float, default=1.0,
                    help="base seconds between searches; a 0-0.6s jitter is added (default 1.0)")
    ap.add_argument("--dry-run", action="store_true",
                    help="search and print matches, but do NOT create the playlist")
    args = ap.parse_args()

    try:
        from ytmusicapi import YTMusic
    except ImportError:
        sys.exit("ytmusicapi not installed. Run:  pip install ytmusicapi")

    try:
        yt = YTMusic(args.auth)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"auth failed ({e}). Re-run `ytmusicapi browser` to refresh {args.auth}.")

    songs = load_songs(args.songs)
    if not songs:
        sys.exit(f"no songs found in {args.songs}")
    print(f"[info] {len(songs)} songs to look up (filter={args.filter}, pace~{args.pace}s)\n")

    matched, missing = [], []
    for i, song in enumerate(songs, 1):
        query = f"{args.artist} {song}".strip()
        try:
            results = yt.search(query, filter=args.filter)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(songs)}] {song}  -> search error: {e}")
            missing.append(song)
            continue
        if not results:
            print(f"[{i}/{len(songs)}] {song}  -> NO MATCH")
            missing.append(song)
        else:
            top = results[0]
            matched.append((song, top))
            print(f"[{i}/{len(songs)}] {song}  -> {artists_str(top)} — {top.get('title')}"
                  f"  [{top.get('videoId')}]")
        if i < len(songs) and args.pace:
            time.sleep(args.pace + random.uniform(0, 0.6))

    print(f"\n[info] matched {len(matched)}/{len(songs)}"
          + (f"; missing: {', '.join(missing)}" if missing else ""))

    if args.dry_run:
        print("\n[dry-run] nothing created. Re-run without --dry-run to build the playlist.")
        return
    if not matched:
        sys.exit("nothing to add.")

    print(f"\n[create] '{args.title}' ({args.privacy}) ...")
    pid = yt.create_playlist(args.title, args.desc or args.title, privacy_status=args.privacy)
    if not isinstance(pid, str):
        sys.exit(f"create_playlist returned unexpected value: {pid!r}")

    video_ids = [top["videoId"] for _, top in matched if top.get("videoId")]
    yt.add_playlist_items(pid, video_ids, duplicates=True)  # order preserved
    print(f"[done] added {len(video_ids)} songs.")
    print(f"[done] https://music.youtube.com/playlist?list={pid}")
    if missing:
        print(f"[note] not added (no match): {', '.join(missing)}")


if __name__ == "__main__":
    main()
