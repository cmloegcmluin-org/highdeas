@echo off
echo.
echo   Saves your Notesnook Inbox API key so the app can post notes.
echo   (In Notesnook: Settings ^> Inbox ^> Enable Inbox API ^> View API Keys ^> +)
echo.
set /p KEY="  Paste your Notesnook key, then press Enter: "
> "%~dp0.env" echo NOTESNOOK_INBOX_API_KEY=%KEY%
echo.
echo   Saved. Close this window, then launch "Review Voice Memos.bat".
echo.
pause
