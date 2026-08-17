"""Highdeas says its own name in the Windows task list.

Windows takes what it shows about a process -- the Details tab's name, the
Processes tab's description, the icon beside it -- from the file the process was
started from, so a plain ``pythonw.exe`` puts Highdeas in the task list as one more
anonymous "Python".  That costs nothing until something strands a process, and
then the task list is the only way back and cannot say which row is safe to end
among half a dozen identical ones belonging to different apps.

``app_support.process_identity`` makes a copy of the interpreter named,
described and marked for this app.  This process cannot be named on the way in
-- writing the copy takes the very interpreter being named -- so each run makes
it for the run after, and the shortcut is pointed at it once it exists.
"""
from __future__ import annotations

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_NAME = "Highdeas"
# Nothing here imports app_support: this suite runs on macOS too, where
# naming a Windows process means nothing, and everything checked below is
# in the source it reads.  What the rule itself produces -- the file name,
# the description -- is app_support's own suite to check.
ROLE = "Highdeas"

ENTRY_POINT = (PROJECT_DIR / "src/highdeas/app.py").read_text(encoding="utf-8")


def test_the_app_prepares_the_copy_for_next_time():
    assert 'ProcessNamer("Highdeas", icon=icon).prepare_launcher("Highdeas")' in ENTRY_POINT



def test_it_stamps_its_own_mark():
    assert (PROJECT_DIR / "highdeas.ico").is_file()


def test_naming_never_takes_a_launch_down():
    """A read-only venv or an antivirus hold must cost the name in the task list
    and nothing else -- this app has no console for a failure to land in."""
    body = ENTRY_POINT[ENTRY_POINT.index('def _name_this_process'):]
    body = body[:body.index("\ndef ", 1)]

    assert "except Exception:" in body
