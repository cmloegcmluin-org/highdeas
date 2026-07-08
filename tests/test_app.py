from pathlib import Path

from voicememo.app import default_bin_dir


def test_default_bin_dir_sits_beside_the_inbox(tmp_path):
    # The bin must live in the same parent folder as the inbox, so retiring a
    # recording (inbox -> bin) moves it *within* the same iCloud tree. Moving a
    # file out of the iCloud folder makes iCloud Drive on Windows pop a per-file
    # "move off iCloud" confirmation dialog for every Submit/Trash.
    inbox = tmp_path / "VoiceInbox"

    result = Path(default_bin_dir(str(inbox)))

    assert result == tmp_path / "VoiceBin"
    assert result.parent == inbox.parent
