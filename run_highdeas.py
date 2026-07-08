"""Windowless launcher for the Highdeas app (used by the taskbar shortcut)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from highdeas.app import main

if __name__ == "__main__":
    main()
