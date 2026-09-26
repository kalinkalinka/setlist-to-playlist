"""The set-up page: it must only answer its own page, and check what it saves."""

import http.client
import http.server
import json
import pathlib
import threading

import pytest

from setlist_playlist import cli, setup_wizard, signin_page, spotify


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("SETLISTFM_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(spotify, "CLIENT_ID_PATH", setup_wizard.config_dir() / "spotify_client_id")
    monkeypatch.setattr(spotify, "TOKEN_PATH", setup_wizard.config_dir() / "spotify.json")
    return tmp_path


@pytest.fixture
def page(home):
    setup = signin_page._Setup(setup_wizard.config_dir() / "browser.json")
    port = {}
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), signin_page._handler_for(setup, "TOKEN", port))
    port["port"] = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield setup, port["port"]
    server.shutdown()
    server.server_close()


def _call(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    sent = {"Host": f"127.0.0.1:{port}"}
    if body is not None:
        sent["Content-Type"] = "application/json"
        body = json.dumps(body)
    sent.update(headers or {})
    conn.request(method, path, body=body, headers=sent)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


def test_serves_the_page_only_under_its_secret_address(page):
    _, port = page
    assert _call(port, "GET", "/TOKEN/")[0] == 200
    assert _call(port, "GET", "/")[0] == 404
    assert _call(port, "GET", "/WRONG/")[0] == 404


def test_refuses_a_request_under_another_host_name(page):
    _, port = page
    assert _call(port, "GET", "/TOKEN/", headers={"Host": "evil.example"})[0] == 404


def test_refuses_posts_from_other_web_pages(page):
    _, port = page
    status, _ = _call(port, "POST", "/TOKEN/service", {"service": "ytmusic"},
                      headers={"Origin": "https://evil.example"})
    assert status == 403


def test_refuses_form_posts(page):
    _, port = page
    status, _ = _call(port, "POST", "/TOKEN/service", {"service": "ytmusic"},
                      headers={"Content-Type": "text/plain"})
    assert status == 415


def test_saves_the_service_choice(page):
    _, port = page
    status, data = _call(port, "POST", "/TOKEN/service", {"service": "ytmusic"})
    assert status == 200 and json.loads(data)["ok"]
    assert setup_wizard.load_config()["service"] == "ytmusic"


def test_the_file_route_is_not_saved_as_a_service(page):
    _, port = page
    _call(port, "POST", "/TOKEN/service", {"service": "file"})
    assert "service" not in setup_wizard.load_config()


def test_rejects_something_that_is_not_a_spotify_client_id(page):
    _, port = page
    _, data = _call(port, "POST", "/TOKEN/spotify-client", {"client_id": "my secret"})
    assert not json.loads(data)["ok"]
    assert not spotify.CLIENT_ID_PATH.exists()


def test_saves_a_spotify_client_id(page):
    _, port = page
    _, data = _call(port, "POST", "/TOKEN/spotify-client", {"client_id": "a" * 32})
    assert json.loads(data)["ok"]
    assert spotify.CLIENT_ID_PATH.read_text().strip() == "a" * 32


def test_rejects_text_that_is_not_a_copied_youtube_request(page):
    setup, port = page
    _, data = _call(port, "POST", "/TOKEN/ytmusic", {"curl": "hello"})
    assert not json.loads(data)["ok"]
    assert not setup.auth_path.exists()


def test_never_sends_a_saved_secret_back(page):
    _, port = page
    _call(port, "POST", "/TOKEN/spotify-client", {"client_id": "b" * 32})
    _, data = _call(port, "GET", "/TOKEN/status")
    assert "b" * 32 not in data.decode()


def test_finish_releases_the_waiting_command(page):
    setup, port = page
    _call(port, "POST", "/TOKEN/finish", {})
    assert setup.done.is_set()


def test_a_missing_setlistfm_key_is_a_next_step_not_an_error(home, capsys):
    assert cli.main(["setlist", "Amon Amarth"]) == 0
    out = capsys.readouterr().out
    assert "NEXT STEP FOR YOU" in out and "setlist-playlist setup" in out


def test_a_garbled_length_is_refused_not_crashed(page):
    _, port = page
    status, _ = _call(port, "POST", "/TOKEN/service", {"service": "ytmusic"},
                      headers={"Content-Length": "lots"})
    assert status in (400, 413)


def test_a_failing_step_answers_instead_of_dropping_the_page(home):
    setup = signin_page._Setup(setup_wizard.config_dir() / "browser.json")

    def explode(data):
        raise TimeoutError("slow")

    setup.save_service = explode  # before the handler is built, so it is used
    port = {}
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), signin_page._handler_for(setup, "TOKEN", port))
    port["port"] = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, data = _call(port["port"], "POST", "/TOKEN/service", {"service": "ytmusic"})
    finally:
        server.shutdown()
        server.server_close()
    assert status == 200
    assert not json.loads(data)["ok"]


def test_a_setlistfm_timeout_is_reported_plainly(home, monkeypatch):
    from setlist_playlist import setlistfm

    def slow(self, name):
        raise TimeoutError("timed out")

    monkeypatch.setattr(setlistfm.SetlistFm, "find_artist", slow)
    setup = signin_page._Setup(setup_wizard.config_dir() / "browser.json")
    ok, message = setup.save_setlistfm({"key": "0123456789abcdef-0123"})
    assert not ok and "too long" in message
