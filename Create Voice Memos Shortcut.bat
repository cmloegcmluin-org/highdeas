@echo off
setlocal
set "ROOT=%~dp0"
set "PYW=%ROOT%.venv\Scripts\pythonw.exe"
set "TARGET=%ROOT%run_voicememo.py"
set "ICON=%ROOT%voicememo.ico"
set "VBS=%TEMP%\_vm_make_shortcut.vbs"
> "%VBS%" echo Set s = CreateObject("WScript.Shell")
>> "%VBS%" echo Set lnk = s.CreateShortcut(s.SpecialFolders("Desktop") ^& "\Voice Memos.lnk")
>> "%VBS%" echo lnk.TargetPath = "%PYW%"
>> "%VBS%" echo lnk.Arguments = "%TARGET%"
>> "%VBS%" echo lnk.WorkingDirectory = "%ROOT:~0,-1%"
>> "%VBS%" echo lnk.IconLocation = "%ICON%"
>> "%VBS%" echo lnk.Description = "Voice Memos"
>> "%VBS%" echo lnk.Save
cscript //nologo "%VBS%"
del "%VBS%"
echo.
echo Done. "Voice Memos" is now on your Desktop.
echo Right-click it and choose "Pin to taskbar" to launch it from there like any app.
echo.
pause
