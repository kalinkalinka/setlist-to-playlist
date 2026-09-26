"""The step-by-step terminal mode, driven with scripted answers."""

import pathlib

import pytest

from setlist_playlist import cli, guided, setup_wizard
from setlist_playlist.setlistfm import Show, Song


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("SETLISTFM_API_KEY", "test-key")
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: None)
    show = Show(date="21-05-2026", artist="Amon Amarth", venue="PH Live",
                city="Las Vegas", country="United States", tour=None, url="u",
                songs=[Song("Intro"), Song("Raven's Flight"), Song("Shield Wall")])
    monkeypatch.setattr(guided, "setlist_for", lambda band: (show, list(show.songs), []))
    return tmp_path


def _answers(monkeypatch, *replies):
    queue = list(replies)
    monkeypatch.setattr("builtins.input", lambda *_: queue.pop(0))
    return queue


class FakeService:
    name, label = "ytmusic", "YouTube Music"

    def __init__(self):
        self.created = None

    def find_song(self, artist, title):
        return {"videoId": title[:11].ljust(11, "x"), "title": title,
                "artists": [{"name": artist}]}

    def track_details(self, track_id):
        return {"videoId": track_id, "title": "Chosen", "artists": [{"name": "Amon Amarth"}]}

    def create_playlist(self, title, description, matches, privacy):
        self.created = (title, [m["title"] for m in matches], privacy)
        return "https://music.youtube.com/playlist?list=TEST"


def test_drops_songs_then_builds_a_private_playlist(home, monkeypatch):
    service = FakeService()
    monkeypatch.setattr(cli, "open_service", lambda args: service)
    queue = _answers(monkeypatch,
                     "Amon Amarth",  # which band
                     "1",            # drop the intro
                     "",             # happy with what's left
                     "",             # YouTube Music (default)
                     "",             # recordings all good
                     "",             # create it
                     "n")            # don't open it
    assert guided.run() == 0
    assert service.created == ("Amon Amarth 2026 Setlist",
                               ["Raven's Flight", "Shield Wall"], "PRIVATE")
    assert setup_wizard.load_config()["service"] == "ytmusic"
    assert not queue


def test_fixing_a_recording_is_used_and_remembered(home, monkeypatch):
    service = FakeService()
    monkeypatch.setattr(cli, "open_service", lambda args: service)
    _answers(monkeypatch, "Amon Amarth", "", "",
             "2", "https://music.youtube.com/watch?v=VQ-BgC58QnQ",  # fix song 2
             "", "", "n")
    assert guided.run() == 0
    assert service.created[1] == ["Intro", "Chosen", "Shield Wall"]
    from setlist_playlist import corrections
    assert corrections.lookup("ytmusic", "Amon Amarth", "Raven's Flight") == "VQ-BgC58QnQ"


def test_another_app_saves_a_file_instead(home, monkeypatch):
    _answers(monkeypatch, "Amon Amarth", "", "3", "n")
    assert guided.run() == 0
    assert (home / "Downloads" / "Amon Amarth 2026 Setlist.csv").is_file()


def test_bad_song_numbers_are_asked_again(home, monkeypatch):
    _answers(monkeypatch, "Amon Amarth", "9", "x", "", "3", "n")
    assert guided.run() == 0


def test_ctrl_c_stops_cleanly(home, monkeypatch, capsys):
    def interrupt(*_):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert guided.run() == 130
    assert "Nothing else was changed" in capsys.readouterr().out


def test_fixing_one_of_two_plays_of_a_song_leaves_the_other(home, monkeypatch):
    songs = [Song("Intro"), Song("Shield Wall"), Song("Intro")]
    show = Show(date="21-05-2026", artist="Amon Amarth", venue="v", city="c",
                country="x", tour=None, url="u", songs=songs)
    original = [{"videoId": "AAAAAAAAAAA"}, {"videoId": "BBBBBBBBBBB"}, {"videoId": "AAAAAAAAAAA"}]
    _answers(monkeypatch, "3", "https://music.youtube.com/watch?v=VQ-BgC58QnQ", "")
    slots = guided._fix_recordings(FakeService(), show, songs, original)
    assert slots[0]["videoId"] == "AAAAAAAAAAA"
    assert slots[2]["videoId"] == "VQ-BgC58QnQ"
