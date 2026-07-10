@echo off
setlocal
set "ENV=%~dp0.env"
echo.
echo   Saves your Notesnook Inbox API key so the app can post notes.
echo   (In Notesnook: Settings ^> Inbox ^> Enable Inbox API ^> View API Keys ^> +)
echo.
set /p KEY="  Paste your Notesnook key, then press Enter: "
rem Rewrite only this key's line, keeping the rest of .env (e.g. the Asana token).
> "%ENV%.tmp" (
  if exist "%ENV%" findstr /v /b /c:"NOTESNOOK_INBOX_API_KEY=" "%ENV%"
  echo NOTESNOOK_INBOX_API_KEY=%KEY%
)
move /y "%ENV%.tmp" "%ENV%" >nul
echo.
echo   Saved. Close this window, then launch "Run Highdeas.bat".
echo.
pause
