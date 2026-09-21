#!/usr/bin/env python3
"""
curl_to_browserjson.py — make ytmusicapi's browser.json from a Chrome "Copy as cURL".

Newer Chrome removed DevTools' "Copy request headers", but "Copy as cURL" still
contains all request headers (incl. the auth cookie). This reads that cURL from
stdin, extracts the headers, and writes `browser.json` next to this script via
ytmusicapi's own setup — so your login cookie goes clipboard -> local file only,
never through the chat/agent.

Usage (macOS):
  1. Chrome DevTools -> Network, filter "browse", right-click a music.youtube.com
     request -> Copy -> Copy as cURL.
  2. Terminal:
       pbpaste | ~/ytmusic-tools/venv/bin/python ~/ytmusic-tools/curl_to_browserjson.py
"""

import os
import re
import sys

from ytmusicapi import setup

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "browser.json")


def main():
    curl = sys.stdin.read()
    if not curl.strip():
        sys.exit("No input. Did you run `pbpaste | ...` after 'Copy as cURL'?")

    # -H 'name: value'  and  -H "name: value"  (also ANSI-C $'...'), tolerating escapes
    headers = re.findall(r"-H \$?'((?:[^'\\]|\\.)*)'", curl)
    headers += re.findall(r'-H \$?"((?:[^"\\]|\\.)*)"', curl)

    # cookie sometimes comes via -b/--cookie instead of a -H
    if not any(h.lower().startswith("cookie:") for h in headers):
        m = re.search(r"(?:-b|--cookie) \$?'((?:[^'\\]|\\.)*)'", curl)
        if m:
            headers.append("cookie: " + m.group(1))

    if not any(h.lower().startswith("cookie:") for h in headers):
        sys.exit("No cookie header found. Copy an *authenticated* music.youtube.com "
                 "request (filter 'browse') while logged in, then retry.")

    raw = "\n".join(headers)
    setup(filepath=OUT, headers_raw=raw)
    print(f"✓ wrote {OUT}  ({len(headers)} headers). You're authenticated.")


if __name__ == "__main__":
    main()
