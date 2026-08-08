"""Windowless launcher for the Highdeas app (used by the taskbar shortcut).

Windowless is the whole problem when something goes wrong: pythonw.exe has no
console, so a failure on the way up — the virtualenv missing something app.py
imports, above all — prints into nothing. The app just never appears, with no
window, no message and no trace of why. So the launcher catches it and says so
in a dialog, which is the one place this machine can still be told."""
import os
import sys
import traceback
from pathlib import Path

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

# Standard library only, so it still loads when the virtualenv is what's broken.
from highdeas.startup import describe_failure, dialog_for, forget, report

# Beside the record of what this virtualenv last installed, and for the same
# reasons: it is about this virtualenv rather than the checkout, git already
# ignores it, and it never syncs between machines.
STARTUP_ERROR = Path(sys.prefix) / ".highdeas-startup-error"

if __name__ == "__main__":
    try:
        from highdeas.app import main

        # Past the imports is past the failure this records, so any older reason
        # is now describing a machine that has since been fixed.
        forget(STARTUP_ERROR)
        main()
    except Exception as error:  # noqa: BLE001 — the last place this can be reported
        # The traceback first, for a run that does have somewhere to print it —
        # this script from a terminal — since catching what used to propagate
        # would otherwise cost that reader everything Python would have said.
        # Then the short version, which is what a dialog can usefully hold.
        traceback.print_exc()
        report(describe_failure(error, python=sys.executable, repo=ROOT),
               dialog=dialog_for(sys.platform), record=STARTUP_ERROR)
        raise SystemExit(1) from error
