@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Create-HighdeasShortcut.ps1"
if errorlevel 1 (
  echo.
  echo Shortcut creation FAILED. See the error above -- most likely the .venv is
  echo missing. Create it, then run this again.
) else (
  echo.
  echo Done. "Highdeas.lnk" in this folder now carries the app's taskbar identity.
  echo Pin THAT file: right-click Highdeas.lnk and choose "Pin to taskbar".
  echo If a generic python icon is still pinned from before, unpin it first.
)
echo.
pause
