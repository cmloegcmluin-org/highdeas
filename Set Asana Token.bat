@echo off
setlocal
set "ENV=%~dp0.env"
echo.
echo   Saves your Asana personal access token so the app can create tasks.
echo   (Create one at https://app.asana.com/0/my-apps ^> Create new token.)
echo.
set /p KEY="  Paste your Asana token, then press Enter: "
rem Rewrite only this key's line, keeping the rest of .env (e.g. the Notesnook key).
> "%ENV%.tmp" (
  if exist "%ENV%" findstr /v /b /c:"ASANA_ACCESS_TOKEN=" "%ENV%"
  echo ASANA_ACCESS_TOKEN=%KEY%
)
move /y "%ENV%.tmp" "%ENV%" >nul
echo.
echo   Saved. Now list your parent tasks as ASANA_PARENT_TASKS in .env
echo   (see .env.example), then launch "Run Highdeas.bat".
echo.
pause
