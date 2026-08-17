from highdeas.preferences import Preferences, PreferenceStore


def test_auto_play_ships_on_before_any_choice_is_made():
    # A note is opened to be heard, so the box ships ticked — until the reader unticks it.
    assert Preferences().autoplay is True


def test_a_store_with_nothing_saved_yet_reports_the_shipped_default(tmp_path):
    assert PreferenceStore(tmp_path / "preferences.json").load().autoplay is True


def test_the_auto_play_choice_survives_to_the_next_launch(tmp_path):
    # The bug this fixes: on Windows the choice was forgotten on every reopen. Saved on
    # the server, a fresh store — what a relaunched app builds — reads the choice back.
    path = tmp_path / "preferences.json"
    PreferenceStore(path).set_autoplay(False)

    assert PreferenceStore(path).load().autoplay is False


def test_turning_auto_play_back_on_is_remembered_too(tmp_path):
    path = tmp_path / "preferences.json"
    PreferenceStore(path).set_autoplay(False)
    PreferenceStore(path).set_autoplay(True)

    assert PreferenceStore(path).load().autoplay is True


def test_a_pathless_store_keeps_the_defaults_and_persists_nothing():
    # create_app's fallback when no store is wired in (as in its many tests): the
    # choice holds the shipped default for the run and simply isn't remembered —
    # never a crash on a missing path.
    store = PreferenceStore()

    store.set_autoplay(False)  # must not raise

    assert store.load().autoplay is True
