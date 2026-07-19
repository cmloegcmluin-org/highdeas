@echo off
setlocal
set "ENV=%~dp0.env"
echo.
echo   Saves an Asana personal access token so the app can create tasks.
echo   (Create one at https://app.asana.com/0/my-apps ^> Create new token, signed
echo   in as the account you want it for.)
echo.
echo   Leave the name blank for your main account. A second account takes a short
echo   name of your choosing - the same name you then write in front of that
echo   account's task gids in ASANA_PARENT_TASKS, like WORK:1200000000000002=Work.
echo.
set "ACCOUNT="
set /p ACCOUNT="  Account name (blank for your main one): "
call :upper ACCOUNT
set "VAR=ASANA_ACCESS_TOKEN"
if defined ACCOUNT set "VAR=ASANA_ACCESS_TOKEN_%ACCOUNT%"
echo.
set /p KEY="  Paste the token for %VAR%, then press Enter: "
rem Rewrite only this variable's line, keeping the rest of .env - the Notesnook key,
rem and the other account's token, which "ASANA_ACCESS_TOKEN=" cannot match.
> "%ENV%.tmp" (
  if exist "%ENV%" findstr /v /b /c:"%VAR%=" "%ENV%"
  echo %VAR%=%KEY%
)
move /y "%ENV%.tmp" "%ENV%" >nul
echo.
echo   Saved as %VAR%. Now list your parent tasks as ASANA_PARENT_TASKS in .env
echo   (see .env.example), then launch "Run Highdeas.bat".
echo.
pause
exit /b

rem Upper-case the named variable in place: .env variables are upper case, and the
rem Mac reads them case-sensitively, so a lower-cased name would work on this PC and
rem go unfound at the other desk. Delayed expansion is what makes a variable
rem substitutable in a loop, and it is kept inside this one call: switched on around
rem the token being typed, it would eat any "!" out of the pasted token.
:upper
if not defined %~1 goto :eof
setlocal enabledelayedexpansion
set "WORD=!%~1!"
for %%A in (A B C D E F G H I J K L M N O P Q R S T U V W X Y Z) do set "WORD=!WORD:%%A=%%A!"
endlocal & set "%~1=%WORD%"
goto :eof
