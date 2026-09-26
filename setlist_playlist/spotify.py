#!/usr/bin/env python3
"""
spotify.py -- build a Spotify playlist, with a login that lasts.

Spotify, unlike YouTube Music, has an official way to let a program act on your
account. You approve it once in your browser and the permission keeps working:
no cookies to copy, and nothing that quietly expires in a few weeks.

The one-off cost is that Spotify requires the program to be registered. Since
this tool runs on your machine rather than on a server, you register it once
yourself -- it takes about two minutes, and the README explains it. After that
the sign-in is a single click.

Your permission is stored in ~/.config/setlist-to-playlist/spotify.json and
refreshes itself. It is never printed.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import pathlib
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

TOKEN_PATH = pathlib.Path.home() / ".config" / "setlist-to-playlist" / "spotify.json"
CLIENT_ID_PATH = pathlib.Path.home() / ".config" / "setlist-to-playlist" / "spotify_client_id"

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_ROOT = "https://api.spotify.com/v1/"

REDIRECT_PORT = 8723
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"

# Only what the tool actually does: make a private playlist and add songs to it.
SCOPES = "playlist-modify-private playlist-modify-public"

SETUP_STEPS = f"""\
Spotify needs this tool registered to your account before it can make playlists.
This needs Spotify Premium: on a free account the Web API box in step 5 is
greyed out. Without Premium, press Enter below to skip, then use
    setlist-playlist setlist "<band>" --save setlist.csv
and import the file with TuneMyMusic (tunemymusic.com), which works on free
Spotify too.

With Premium you do this once, and it takes about two minutes:

  1. Go to  https://developer.spotify.com/dashboard  and log in.
  2. Click  Create app.
  3. Name it anything (for example: setlist-to-playlist).
  4. In  Redirect URIs  enter exactly:
         {REDIRECT_URI}
  5. Tick the Web API box, agree to the terms, and save.
  6. Open the app's  Settings  and copy the  Client ID.
     (There is also a client secret. This tool does not need it. Leave it alone.)

Then save the Client ID:

    echo 'YOUR-CLIENT-ID' > {CLIENT_ID_PATH}
"""


class SpotifyError(RuntimeError):
    """Something went wrong with Spotify."""


def load_client_id(explicit: str | None = None) -> str:
    if explicit:
        return explicit.strip()
    env = os.environ.get("SPOTIFY_CLIENT_ID")
    if env and env.strip():
        return env.strip()
    if CLIENT_ID_PATH.is_file():
        value = CLIENT_ID_PATH.read_text().strip()
        if value:
            return value
    raise SpotifyError(SETUP_STEPS)


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:300]
        raise SpotifyError(f"Spotify refused the sign-in (HTTP {err.code}): {detail}") from err


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Catches the one redirect Spotify sends back after you approve."""

    result: dict = {}

    def do_GET(self):  # noqa: N802 - name fixed by the library
        query = urllib.parse.urlparse(self.path).query
        _CallbackHandler.result = dict(urllib.parse.parse_qsl(query))
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in _CallbackHandler.result
        message = (
            "<h2>You're signed in.</h2><p>Close this tab and go back to the terminal.</p>"
            if ok else
            "<h2>Sign-in failed.</h2><p>Go back to the terminal for details.</p>"
        )
        self.wfile.write(f"<html><body style='font-family:sans-serif'>{message}</body></html>".encode())

    def log_message(self, *args):  # keep the terminal quiet
        return


def sign_in(client_id: str | None = None, token_path: pathlib.Path = TOKEN_PATH) -> dict:
    """Ask Spotify for permission, in the browser, once.

    Uses the flow Spotify recommends for programs that run on someone's own
    computer, which needs no client secret.
    """
    client_id = load_client_id(client_id)

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    state = secrets.token_urlsafe(16)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)

    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), _CallbackHandler)
    server.timeout = 120
    _CallbackHandler.result = {}

    print("Opening Spotify in your browser to ask for permission...")
    print(f"If nothing opens, go to:\n{url}\n")
    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    server.handle_request()
    server.server_close()

    result = _CallbackHandler.result
    if result.get("state") != state:
        raise SpotifyError("The reply from Spotify did not match the request. Try again.")
    if "code" not in result:
        raise SpotifyError(
            "Spotify did not grant permission"
            + (f": {result['error']}" if result.get("error") else ".")
        )

    tokens = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
    })
    tokens["client_id"] = client_id
    _save_tokens(tokens, token_path)
    print("Spotify is connected.\n")
    return tokens


def _save_tokens(tokens: dict, token_path: pathlib.Path = TOKEN_PATH) -> None:
    tokens = dict(tokens)
    tokens["expires_at"] = time.time() + float(tokens.get("expires_in", 3600)) - 60
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(tokens, indent=2))
    token_path.chmod(0o600)


def _load_tokens(token_path: pathlib.Path = TOKEN_PATH) -> dict | None:
    if not token_path.is_file():
        return None
    try:
        return json.loads(token_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


class Spotify:
    """A small client for the handful of things this tool does."""

    def __init__(self, token_path: pathlib.Path = TOKEN_PATH, interactive: bool = True):
        self.token_path = pathlib.Path(token_path).expanduser()
        tokens = _load_tokens(self.token_path)
        if not tokens:
            if not interactive:
                raise SpotifyError(
                    "Spotify is not connected yet. Run:\n    setlist-playlist login --service spotify"
                )
            tokens = sign_in(token_path=self.token_path)
        self.tokens = tokens

    def _access_token(self) -> str:
        if time.time() < self.tokens.get("expires_at", 0):
            return self.tokens["access_token"]

        refresh = self.tokens.get("refresh_token")
        if not refresh:
            raise SpotifyError(
                "Spotify needs connecting again. Run:\n    setlist-playlist login --service spotify"
            )
        fresh = _post_form(TOKEN_URL, {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": self.tokens["client_id"],
        })
        fresh.setdefault("refresh_token", refresh)
        fresh["client_id"] = self.tokens["client_id"]
        _save_tokens(fresh, self.token_path)
        self.tokens = _load_tokens(self.token_path)
        return self.tokens["access_token"]

    def _request(self, method: str, path: str, params: dict | None = None,
                 payload: dict | None = None) -> dict:
        url = API_ROOT + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as err:
            if err.code == 401:
                raise SpotifyError(
                    "Spotify rejected the login. Reconnect with:\n"
                    "    setlist-playlist login --service spotify"
                ) from err
            if err.code == 429:
                raise SpotifyError("Spotify is rate-limiting us. Wait a minute and try again.") from err
            raise SpotifyError(f"Spotify returned HTTP {err.code}.") from err

    def me(self) -> dict:
        return self._request("GET", "me")

    def find_song(self, artist: str, title: str) -> dict | None:
        """Find one song.

        Spotify lets us say which part is the artist and which is the title,
        rather than hoping a single string of words ranks correctly.
        """
        query = f'track:"{title}" artist:"{artist}"'
        found = self._request("GET", "search", {"q": query, "type": "track", "limit": 5})
        items = (found.get("tracks") or {}).get("items") or []
        if not items:
            # Fall back to a looser search for titles written differently.
            found = self._request("GET", "search",
                                  {"q": f"{artist} {title}", "type": "track", "limit": 5})
            items = (found.get("tracks") or {}).get("items") or []
        if not items:
            return None
        track = items[0]
        return {
            "id": track["id"],
            "uri": track["uri"],
            "title": track["name"],
            "artists": [{"name": a["name"]} for a in track.get("artists", [])],
        }

    def track_details(self, track_id: str) -> dict | None:
        try:
            track = self._request("GET", f"tracks/{track_id}")
        except SpotifyError:
            return None
        return {
            "id": track["id"],
            "uri": track["uri"],
            "title": track["name"],
            "artists": [{"name": a["name"]} for a in track.get("artists", [])],
        }

    def create_playlist(self, title: str, description: str, track_uris: list[str],
                        public: bool = False) -> str:
        user_id = self.me()["id"]
        playlist = self._request("POST", f"users/{user_id}/playlists", payload={
            "name": title,
            "description": description,
            "public": public,
        })
        # Spotify takes 100 songs per request.
        for start in range(0, len(track_uris), 100):
            self._request("POST", f"playlists/{playlist['id']}/tracks",
                          payload={"uris": track_uris[start:start + 100]})
        return playlist["external_urls"]["spotify"]
