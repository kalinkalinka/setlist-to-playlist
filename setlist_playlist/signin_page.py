#!/usr/bin/env python3
"""
signin_page.py -- the set-up steps as a page in your browser.

Signing in is the one part of this tool a person has to do by hand, and the
terminal is the worst place to do it: people paste logins into the shell, where
they land in its history, and anyone using the tool through Claude or Codex may
never have opened a terminal at all. So `setlist-playlist setup` opens a small
page on this computer that walks through it one step at a time and checks each
answer actually works before saving it.

An agent can run the command on someone's behalf: the page opens in their
browser, they follow it, and the command returns once they press Finish.

The page is served on 127.0.0.1 only, under a random address that changes every
run, and refuses requests from any other web page. Nothing typed into it is
ever shown back, printed, or sent anywhere except the service it belongs to.
"""

from __future__ import annotations

import http.server
import json
import os
import pathlib
import re
import secrets
import tempfile
import threading
import webbrowser

from . import setup_wizard

MAX_BODY = 256 * 1024  # a copied request is a few kilobytes; refuse anything silly
SERVICES = {"spotify": "Spotify", "ytmusic": "YouTube Music", "file": "another app (via a file)"}


class _Setup:
    """What the page can do. Kept apart from the web server so it can be tested."""

    def __init__(self, auth_path: pathlib.Path):
        self.auth_path = auth_path
        self.done = threading.Event()
        self.chosen: str | None = setup_wizard.load_config().get("service")

    # -- what is already in place ------------------------------------------

    def status(self) -> dict:
        from . import spotify
        from .setlistfm import SetlistFmError, load_api_key

        try:
            load_api_key()
            has_key = True
        except SetlistFmError:
            has_key = False
        return {
            "setlistfm": has_key,
            "service": self.chosen,
            "ytmusic": self.auth_path.is_file(),
            "spotify_client": spotify.CLIENT_ID_PATH.is_file(),
            "spotify": spotify.TOKEN_PATH.is_file(),
            "spotify_redirect": spotify.REDIRECT_URI,
        }

    # -- one handler per step; each returns (ok, message) -------------------

    def save_setlistfm(self, data: dict) -> tuple[bool, str]:
        from .setlistfm import SetlistFm, SetlistFmError

        key = str(data.get("key", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", key):
            return False, ("That doesn't look like a setlist.fm API key. It's a long "
                           "mix of letters, numbers and dashes, shown on the page "
                           "after you submit their form.")
        try:
            SetlistFm(api_key=key).find_artist("Metallica")
        except SetlistFmError as err:
            text = str(err)
            if "401" in text or "403" in text or "key" in text.lower():
                return False, ("setlist.fm did not accept that key. Copy it again "
                               "from setlist.fm, with nothing before or after it.")
            return False, f"Could not reach setlist.fm to check the key: {text}"
        target = setup_wizard.key_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(key + "\n")
        target.chmod(0o600)
        return True, "Saved. setlist.fm accepted your key."

    def save_service(self, data: dict) -> tuple[bool, str]:
        service = data.get("service")
        if service not in SERVICES:
            return False, "Pick one of the options."
        self.chosen = service
        if service in ("spotify", "ytmusic"):
            config = setup_wizard.load_config()
            config["service"] = service
            setup_wizard.save_config(config)
        return True, f"Playlists will go to {SERVICES[service]}."

    def save_ytmusic(self, data: dict) -> tuple[bool, str]:
        from . import ytmusic

        curl = str(data.get("curl", ""))
        if "music.youtube.com" not in curl or "curl" not in curl:
            return False, ("That isn't the copied request. In Chrome's Network tab, "
                           'right-click a row named "browse", then Copy > Copy as cURL, '
                           "and paste again.")
        # Save to a scratch file first; only a login that works replaces the old one.
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        handle, scratch = tempfile.mkstemp(dir=self.auth_path.parent, suffix=".tmp")
        os.close(handle)
        scratch_path = pathlib.Path(scratch)
        try:
            ytmusic.save_login(curl, scratch_path)
            session = ytmusic._require_ytmusicapi().YTMusic(str(scratch_path))
            session.get_library_playlists(limit=1)
        except ytmusic.YouTubeMusicError as err:
            scratch_path.unlink(missing_ok=True)
            return False, str(err)
        except Exception:  # noqa: BLE001 - the library raises several types
            scratch_path.unlink(missing_ok=True)
            return False, ("YouTube Music did not accept that login. Make sure the "
                           "Chrome tab is signed in, reload it, and copy a fresh "
                           '"browse" row.')
        os.replace(scratch_path, self.auth_path)
        self.auth_path.chmod(0o600)
        return True, "Saved. YouTube Music accepted your login."

    def save_spotify_client(self, data: dict) -> tuple[bool, str]:
        from . import spotify

        client_id = str(data.get("client_id", "")).strip()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", client_id):
            return False, ("A Client ID is 32 letters and numbers, shown under the "
                           "app's Settings. (Not the client secret.)")
        spotify.CLIENT_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
        spotify.CLIENT_ID_PATH.write_text(client_id + "\n")
        spotify.CLIENT_ID_PATH.chmod(0o600)
        return True, ("Saved. When you press Finish, Spotify will open and ask you "
                      "to allow access.")

    def finish(self, data: dict) -> tuple[bool, str]:
        self.done.set()
        return True, "All done. You can close this tab."


def _handler_for(setup: _Setup, token: str, port_holder: dict):
    actions = {
        "setlistfm": setup.save_setlistfm,
        "service": setup.save_service,
        "ytmusic": setup.save_ytmusic,
        "spotify-client": setup.save_spotify_client,
        "finish": setup.finish,
    }
    prefix = f"/{token}/"

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the terminal quiet; bodies hold logins
            pass

        def _host_ok(self) -> bool:
            # Refuse DNS-rebinding tricks: the browser must be talking to us by IP.
            port = port_holder["port"]
            return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def _send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "script-src 'unsafe-inline'; connect-src 'self'; "
                             "img-src 'self' data:; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload: dict) -> None:
            self._send(code, json.dumps(payload).encode(), "application/json")

        def do_GET(self):  # noqa: N802 - name fixed by the library
            if not self._host_ok() or not self.path.startswith(prefix):
                return self._send(404, b"Not found", "text/plain")
            rest = self.path[len(prefix):]
            if rest in ("", "index.html"):
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if rest == "status":
                return self._json(200, setup.status())
            return self._send(404, b"Not found", "text/plain")

        def do_POST(self):  # noqa: N802
            if not self._host_ok() or not self.path.startswith(prefix):
                return self._send(404, b"Not found", "text/plain")
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                return self._json(403, {"ok": False, "message": "Refused."})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self._json(415, {"ok": False, "message": "Refused."})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._json(413, {"ok": False, "message": "That is too long."})
            action = actions.get(self.path[len(prefix):])
            if action is None:
                return self._send(404, b"Not found", "text/plain")
            try:
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError
            except ValueError:
                return self._json(400, {"ok": False, "message": "Refused."})
            ok, message = action(data)
            return self._json(200, {"ok": ok, "message": message, "status": setup.status()})

    return Handler


def run(auth_path: pathlib.Path, timeout_minutes: int = 30, open_browser: bool = True) -> dict:
    """Serve the page until the person presses Finish (or time runs out).

    Returns the final status so the caller can say what is now in place.
    """
    setup = _Setup(auth_path)
    token = secrets.token_urlsafe(24)
    port_holder: dict = {}
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler_for(setup, token, port_holder)
    )
    port_holder["port"] = server.server_address[1]
    url = f"http://127.0.0.1:{port_holder['port']}/{token}/"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if open_browser:
        print("Opening the set-up page in your browser.")
        print(f"If it doesn't open, copy this address into your browser:\n    {url}\n")
    else:
        print(f"Open this address in your browser:\n    {url}\n")
    print("Waiting for you to press Finish on the page...", flush=True)
    if open_browser:
        webbrowser.open(url)

    finished = setup.done.wait(timeout_minutes * 60)
    server.shutdown()
    server.server_close()
    status = setup.status()
    status["finished"] = finished
    return status


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Setlist to Playlist set-up</title>
<style>
:root {
  --bg: #f6f5f2; --card: #ffffff; --text: #1d1d1f; --muted: #5f5f66;
  --line: #e2e0da; --accent: #b3261e; --accent-text: #ffffff;
  --ok: #1e7a3c; --ok-bg: #e6f4ea; --bad: #a3231b; --bad-bg: #fbe9e7;
  --code: #efeee9;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #141416; --card: #1f1f23; --text: #ececf0; --muted: #a2a2ab;
    --line: #34343a; --accent: #e5534b; --accent-text: #141416;
    --ok: #6fd08c; --ok-bg: #173323; --bad: #ff8a80; --bad-bg: #3a1c1a;
    --code: #2a2a30;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
main { max-width: 640px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 26px; margin: 0 0 4px; }
.sub { color: var(--muted); margin: 0 0 24px; }
.progress { display: flex; gap: 6px; margin-bottom: 20px; }
.progress span { flex: 1; height: 4px; border-radius: 2px; background: var(--line); }
.progress span.on { background: var(--accent); }
section { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  padding: 22px; display: none; }
section.active { display: block; }
h2 { font-size: 19px; margin: 0 0 10px; }
ol { padding-left: 22px; margin: 10px 0 16px; }
li { margin: 6px 0; }
.hint { color: var(--muted); font-size: 14px; }
code, kbd { background: var(--code); border-radius: 4px; padding: 1px 5px;
  font: 14px ui-monospace, SFMono-Regular, Menlo, monospace; }
input[type=text], input[type=password], textarea { width: 100%; padding: 10px 12px;
  border: 1px solid var(--line); border-radius: 8px; background: var(--bg);
  color: var(--text); font: 14px ui-monospace, SFMono-Regular, Menlo, monospace; }
textarea { height: 110px; resize: vertical; }
button { font: inherit; font-weight: 600; border: 0; border-radius: 8px;
  padding: 10px 18px; cursor: pointer; background: var(--accent); color: var(--accent-text); }
button.plain { background: transparent; color: var(--muted); border: 1px solid var(--line); }
button:disabled { opacity: .5; cursor: wait; }
.row { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; align-items: center; }
.choice { display: block; border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; margin: 10px 0; cursor: pointer; }
.choice:has(input:checked) { border-color: var(--accent); }
.choice input { margin-right: 8px; }
.choice small { display: block; color: var(--muted); margin-left: 24px; }
.msg { margin-top: 12px; padding: 10px 12px; border-radius: 8px; display: none; }
.msg.ok { display: block; background: var(--ok-bg); color: var(--ok); }
.msg.bad { display: block; background: var(--bad-bg); color: var(--bad); }
.done-list li { list-style: none; margin-left: -22px; }
a { color: var(--accent); }
</style>
</head>
<body>
<main>
  <h1>Setlist to Playlist</h1>
  <p class="sub">Turns a band's latest concert into a playlist you can play.
  This page sets it up once; after that you just ask for a band.</p>
  <div class="progress" id="progress"></div>

  <section id="s-welcome">
    <h2>What you'll do here</h2>
    <ol>
      <li><b>Get a setlist.fm key</b> &mdash; free, about a minute. It's how the tool
        looks up what a band played.</li>
      <li><b>Choose where playlists go</b> &mdash; Spotify, YouTube Music, or any other app.</li>
      <li><b>Connect that app</b> &mdash; only if you picked Spotify or YouTube Music.</li>
    </ol>
    <p class="hint">Everything you enter stays on this computer and goes only to the
      service it belongs to. It is never shown back or shared.</p>
    <div class="row"><button onclick="next()">Start</button></div>
  </section>

  <section id="s-setlistfm">
    <h2>1 &middot; Your setlist.fm key</h2>
    <ol>
      <li>Open <a href="https://www.setlist.fm/settings/api" target="_blank" rel="noopener">setlist.fm &rarr; API settings</a>
        and sign in (or create a free account).</li>
      <li>Fill in the short form. For &ldquo;application name&rdquo; anything works, e.g.
        <code>my playlists</code>; say it's for personal, non-commercial use.</li>
      <li>Submit it. Your key appears on the page straight away &mdash; copy it.</li>
    </ol>
    <input type="password" id="key" placeholder="Paste your setlist.fm API key" autocomplete="off">
    <div class="row"><button onclick="send('setlistfm', {key: val('key')}, this)">Check and save</button><button class="plain" onclick="back()">Back</button>
      <button class="plain" onclick="next()">Skip for now</button></div>
    <div class="msg" id="m-setlistfm"></div>
  </section>

  <section id="s-service">
    <h2>2 &middot; Where should playlists go?</h2>
    <label class="choice"><input type="radio" name="svc" value="ytmusic">YouTube Music
      <small>Free. You copy a login from Chrome once; it expires every few weeks and you repeat it.</small></label>
    <label class="choice"><input type="radio" name="svc" value="spotify">Spotify (Premium only)
      <small>Spotify only allows this on paid accounts. One two-minute registration, then it keeps working.</small></label>
    <label class="choice"><input type="radio" name="svc" value="file">Another app &mdash; Apple Music, Amazon Music, Tidal, Deezer, free Spotify&hellip;
      <small>Nothing to connect. You get a file and import it with the free TuneMyMusic website.</small></label>
    <div class="row"><button onclick="send('service', {service: picked()}, this)">Continue</button><button class="plain" onclick="back()">Back</button></div>
    <div class="msg" id="m-service"></div>
  </section>

  <section id="s-ytmusic">
    <h2>3 &middot; Connect YouTube Music</h2>
    <p class="hint">Use Google Chrome on this computer.</p>
    <ol>
      <li>Open <a href="https://music.youtube.com" target="_blank" rel="noopener">music.youtube.com</a>, signed in to the account you want.</li>
      <li>Open developer tools: <kbd>Cmd</kbd>+<kbd>Option</kbd>+<kbd>I</kbd> on a Mac,
        <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>I</kbd> on Windows.</li>
      <li>Click the <b>Network</b> tab at the top of the panel, then reload the page
        (<kbd>Cmd</kbd>+<kbd>R</kbd> / <kbd>Ctrl</kbd>+<kbd>R</kbd>).</li>
      <li>In the Network tab's <b>filter</b> box, type <code>browse</code>.</li>
      <li><b>The list may look empty. Scroll down inside it</b> until you see rows
        named <code>browse</code>. None at all? Reload the page again.</li>
      <li>Right-click a <code>browse</code> row &rarr; <b>Copy</b> &rarr; <b>Copy as cURL</b>
        (plain &ldquo;Copy as cURL&rdquo;, not fetch or PowerShell).</li>
      <li>Paste it below.</li>
    </ol>
    <textarea id="curl" placeholder="Paste the copied request here" spellcheck="false" autocomplete="off"></textarea>
    <p class="hint">This contains your YouTube login. It is checked with YouTube, saved on
      this computer only, and cleared from this box.</p>
    <div class="row"><button onclick="send('ytmusic', {curl: val('curl')}, this, 'curl')">Check and save</button><button class="plain" onclick="back()">Back</button>
      <button class="plain" onclick="next()">Skip for now</button></div>
    <div class="msg" id="m-ytmusic"></div>
  </section>

  <section id="s-spotify">
    <h2>3 &middot; Connect Spotify</h2>
    <ol>
      <li>Open the <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noopener">Spotify developer dashboard</a> and log in.</li>
      <li>Click <b>Create app</b>. Name and description can be anything.</li>
      <li>Under <b>Redirect URIs</b>, enter exactly <code id="redirect"></code> and click Add.</li>
      <li>Tick <b>Web API</b>. If it's greyed out, your account isn't Premium &mdash;
        <a href="#" onclick="choose('file'); return false;">use the file option instead</a>.</li>
      <li>Agree to the terms and save. Open the app's <b>Settings</b> and copy the <b>Client ID</b>
        (not the client secret).</li>
    </ol>
    <input type="text" id="cid" placeholder="Paste the Client ID" autocomplete="off" spellcheck="false">
    <div class="row"><button onclick="send('spotify-client', {client_id: val('cid')}, this)">Save</button><button class="plain" onclick="back()">Back</button>
      <button class="plain" onclick="next()">Skip for now</button></div>
    <div class="msg" id="m-spotify-client"></div>
  </section>

  <section id="s-file">
    <h2>3 &middot; Using another app</h2>
    <p>Nothing to connect. Each time you ask for a band, you get a <code>.csv</code> file. Then:</p>
    <ol>
      <li>Go to <a href="https://www.tunemymusic.com" target="_blank" rel="noopener">tunemymusic.com</a> and click <b>Let's Start</b>.</li>
      <li>Choose <b>Upload file</b> and pick the CSV.</li>
      <li>Choose your app and sign in there, as usual.</li>
      <li>Check the matches and click <b>Start Transfer</b>.</li>
    </ol>
    <p class="hint">If the first song was intro music played from tape, it may not match &mdash; just remove it.</p>
    <div class="row"><button onclick="next()">Continue</button><button class="plain" onclick="back()">Back</button></div>
  </section>

  <section id="s-done">
    <h2 id="done-title">You're set up</h2>
    <ul class="done-list" id="summary"></ul>
    <p>Press Finish. Then ask for any band &mdash; &ldquo;make me a playlist of Iron Maiden's latest show&rdquo;.</p>
    <div class="row"><button onclick="send('finish', {}, this)">Finish</button><button class="plain" onclick="back()">Back</button></div>
    <div class="msg" id="m-finish"></div>
  </section>
</main>
<script>
const base = location.pathname;
let st = {}, flow = [], at = 0;

function val(id) { return document.getElementById(id).value; }
function picked() { const c = document.querySelector('input[name=svc]:checked'); return c ? c.value : ''; }
function choose(v) { document.querySelector('input[name=svc][value=' + v + ']').checked = true;
  send('service', {service: v}); }

function plan() {
  flow = ['welcome'];
  if (!st.setlistfm) flow.push('setlistfm');
  flow.push('service');
  if (st.service === 'ytmusic') flow.push('ytmusic');
  if (st.service === 'spotify' && !st.spotify) flow.push('spotify');
  if (st.service === 'file') flow.push('file');
  flow.push('done');
}
function show(name) {
  plan();
  at = Math.max(0, flow.indexOf(name));
  document.querySelectorAll('section').forEach(s => s.classList.remove('active'));
  document.getElementById('s-' + flow[at]).classList.add('active');
  document.getElementById('progress').innerHTML =
    flow.map((_, i) => '<span class="' + (i <= at ? 'on' : '') + '"></span>').join('');
  if (flow[at] === 'done') summary();
  window.scrollTo(0, 0);
}
function next() { const here = flow[at]; plan(); show(flow[Math.min(flow.indexOf(here) + 1, flow.length - 1)]); }
function back() { const here = flow[at]; plan(); show(flow[Math.max(flow.indexOf(here) - 1, 0)]); }

function summary() {
  const names = {ytmusic: 'YouTube Music', spotify: 'Spotify', file: 'another app, via a CSV file'};
  const lines = [];
  lines.push((st.setlistfm ? '✓ ' : '✗ ') + 'setlist.fm key' + (st.setlistfm ? ' saved' : ' still missing'));
  lines.push('✓ Playlists go to ' + (names[st.service] || 'nowhere yet'));
  if (st.service === 'ytmusic') lines.push((st.ytmusic ? '✓ ' : '✗ ') + 'YouTube Music ' + (st.ytmusic ? 'connected' : 'not connected yet'));
  if (st.service === 'spotify') lines.push((st.spotify ? '✓ Spotify connected' : '→ Spotify will ask for permission when you press Finish'));
  document.getElementById('summary').innerHTML = lines.map(l => '<li>' + l + '</li>').join('');
  const missing = lines.some(l => l.startsWith('\u2717'));
  document.getElementById('done-title').textContent = missing
    ? 'Almost there \u2014 some steps were skipped' : "You're set up";
}

async function send(action, body, btn, clearId) {
  const box = document.getElementById('m-' + action);
  if (btn) btn.disabled = true;
  if (box) { box.className = 'msg'; }
  try {
    const r = await fetch(base + action, {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const d = await r.json();
    if (clearId) document.getElementById(clearId).value = '';
    if (d.status) st = d.status;
    if (box) { box.textContent = d.message; box.className = 'msg ' + (d.ok ? 'ok' : 'bad'); }
    if (d.ok && action === 'finish') {
      document.querySelectorAll('button').forEach(b => b.disabled = true);
      return;
    }
    if (d.ok) setTimeout(next, 700);
  } catch (e) {
    if (box) { box.textContent = 'The set-up command has stopped. Run it again to continue.'; box.className = 'msg bad'; }
  } finally { if (btn && action !== 'finish') btn.disabled = false; }
}

fetch(base + 'status').then(r => r.json()).then(d => {
  st = d;
  document.getElementById('redirect').textContent = d.spotify_redirect;
  if (d.service) { const c = document.querySelector('input[name=svc][value=' + d.service + ']'); if (c) c.checked = true; }
  show('welcome');
});
</script>
</body>
</html>
"""
