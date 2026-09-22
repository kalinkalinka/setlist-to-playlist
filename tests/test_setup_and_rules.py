"""Tests for the decisions this tool makes on your behalf."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from setlist_playlist import corrections, setup_wizard  # noqa: E402
from setlist_playlist.setlistfm import Show, Song, choose_show, clean_songs  # noqa: E402


# --- the first-run question -------------------------------------------------

def _answer(monkeypatch, *replies):
    """Pretend someone is sitting at a terminal typing these answers."""
    queue = list(replies)
    monkeypatch.setattr(setup_wizard.sys, "stdin", type("T", (), {"isatty": lambda self: True})())
    monkeypatch.setattr("builtins.input", lambda *_: queue.pop(0))


def test_first_run_asks_where_playlists_should_go(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    _answer(monkeypatch, "1")

    assert setup_wizard.choose_service(path=config) == "spotify"
    assert config.is_file(), "the answer should be remembered"


def test_choosing_youtube_music(monkeypatch, tmp_path):
    _answer(monkeypatch, "2")
    assert setup_wizard.choose_service(path=tmp_path / "config.json") == "ytmusic"


def test_pressing_enter_takes_the_recommended_option(monkeypatch, tmp_path):
    _answer(monkeypatch, "")
    assert setup_wizard.choose_service(path=tmp_path / "config.json") == "spotify"


def test_it_only_asks_once(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    _answer(monkeypatch, "2")
    setup_wizard.choose_service(path=config)

    def explode(*_):
        raise AssertionError("asked a second time")

    monkeypatch.setattr("builtins.input", explode)
    assert setup_wizard.choose_service(path=config) == "ytmusic"


def test_never_asks_when_nobody_is_there(monkeypatch, tmp_path):
    assert setup_wizard.choose_service(
        interactive=False, path=tmp_path / "config.json") == "ytmusic"


# --- which show counts ------------------------------------------------------

def _show(date, song_count, info=None):
    return Show(date=date, artist="Test Band", venue="Venue", city="City",
                country="Country", tour=None, url="", info=info,
                songs=[Song(title=f"Song {n}") for n in range(song_count)])


def test_skips_a_show_with_no_songs_yet():
    shows = [_show("22-09-2026", 0), _show("18-09-2026", 18)]
    chosen, notes = choose_show(shows)
    assert chosen.date == "18-09-2026"
    assert any("no songs listed yet" in note for note in notes)


def test_skips_a_setlist_marked_incomplete():
    shows = [_show("22-09-2026", 11, info="Setlist incomplete and out of order"),
             _show("18-09-2026", 18)]
    chosen, _ = choose_show(shows)
    assert chosen.date == "18-09-2026"


def test_skips_a_short_festival_slot():
    shows = [_show("22-09-2026", 9)] + [_show(f"1{n}-09-2026", 18) for n in range(5)]
    chosen, notes = choose_show(shows)
    assert chosen.date != "22-09-2026"
    assert any("festival" in note for note in notes)


def test_takes_the_newest_show_when_it_is_a_normal_one():
    shows = [_show("22-09-2026", 17), _show("18-09-2026", 18)]
    chosen, _ = choose_show(shows)
    assert chosen.date == "22-09-2026"


# --- cleaning the setlist ---------------------------------------------------

def test_splits_a_medley():
    songs, notes = clean_songs([Song(title="One / Two / Three")])
    assert [s.title for s in songs] == ["One", "Two", "Three"]
    assert any("medley" in note for note in notes)


def test_drops_solos():
    songs, _ = clean_songs([Song(title="Drum Solo"), Song(title="Guitar Solo"),
                            Song(title="Painkiller")])
    assert [s.title for s in songs] == ["Painkiller"]


def test_drops_walk_on_music_by_someone_else():
    songs, notes = clean_songs([Song(title="War Pigs", tape=True, cover_of="Black Sabbath"),
                                Song(title="Metal Gods")])
    assert [s.title for s in songs] == ["Metal Gods"]
    assert any("Black Sabbath" in note for note in notes)


def test_keeps_a_taped_song_the_band_wrote():
    """Judas Priest play "The Hellion" from tape, and it belongs in the playlist."""
    songs, notes = clean_songs([Song(title="The Hellion", tape=True),
                                Song(title="Electric Eye")])
    assert [s.title for s in songs] == ["The Hellion", "Electric Eye"]
    assert any("band's own song" in note for note in notes)


def test_drops_a_nameless_intro_even_if_the_band_made_it():
    songs, _ = clean_songs([Song(title="Faithkeepers Intro", tape=True),
                            Song(title="Metal Gods")])
    assert [s.title for s in songs] == ["Metal Gods"]


# --- remembering a chosen recording ----------------------------------------

def test_remembers_a_chosen_recording(tmp_path):
    path = tmp_path / "corrections.json"
    corrections.remember("ytmusic", "Accept", "Fast as a Shark", "VQ-BgC58QnQ", path)
    assert corrections.lookup("ytmusic", "Accept", "Fast as a Shark", path) == "VQ-BgC58QnQ"


def test_a_choice_survives_different_capitals_and_spacing(tmp_path):
    path = tmp_path / "corrections.json"
    corrections.remember("ytmusic", "Accept", "Fast as a Shark", "VQ-BgC58QnQ", path)
    assert corrections.lookup("ytmusic", "accept", "  FAST AS A SHARK ", path) == "VQ-BgC58QnQ"


def test_reads_a_track_from_a_share_link():
    assert corrections.track_id_from(
        "https://music.youtube.com/watch?v=VQ-BgC58QnQ&si=abc") == "VQ-BgC58QnQ"
    assert corrections.track_id_from(
        "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT", "spotify"
    ) == "4cOdK2wGLETKBW3PvgPWqT"


def test_one_service_choice_does_not_affect_another(tmp_path):
    path = tmp_path / "corrections.json"
    corrections.remember("ytmusic", "Accept", "Breaker", "aaaaaaaaaaa", path)
    assert corrections.lookup("spotify", "Accept", "Breaker", path) is None
