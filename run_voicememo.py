"""Windowless launcher for the Voice Memos app (used by the taskbar shortcut)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from voicememo.app import main

if __name__ == "__main__":
    main()
