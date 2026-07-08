# Rebuilds Highdeas.lnk with the Windows taskbar identity that makes "Pin to taskbar" work.
#
# A plain shortcut to pythonw.exe has no app identity, so when its window appears Windows
# groups it under pythonw.exe and pins a generic python icon that won't relaunch the app.
# The fix is to stamp the shortcut's System.AppUserModel.ID with the SAME string the app
# sets at runtime (voicememo.app.APP_ID = "Douglas.Highdeas", via
# SetCurrentProcessExplicitAppUserModelID). Matching IDs let Windows merge the running
# window into the pinned shortcut and show voicememo.ico. WScript.Shell can't write that
# property, so this uses the IShellLink + IPropertyStore COM interfaces directly. Modeled
# on FunGenApp's Update-FunGenShortcut.ps1 -- the known-good taskbar recipe.
param(
    [string]$Root,
    [string]$ShortcutPath
)

$ErrorActionPreference = 'Stop'

if (-not $Root) { $Root = $PSScriptRoot }
if (-not $ShortcutPath) { $ShortcutPath = Join-Path $Root 'Highdeas.lnk' }

$AppUserModelId = 'Douglas.Highdeas'   # must match voicememo.app.APP_ID
$Pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
$Script  = Join-Path $Root 'run_voicememo.py'
$Icon    = Join-Path $Root 'voicememo.ico'

foreach ($required in @($Pythonw, $Script, $Icon)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required file not found: $required (is the .venv set up?)"
    }
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

[ComImport]
[Guid("00021401-0000-0000-C000-000000000046")]
class CShellLink {}

[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("000214F9-0000-0000-C000-000000000046")]
interface IShellLinkW
{
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cch, IntPtr pfd, int fFlags);
    void GetIDList(out IntPtr ppidl);
    void SetIDList(IntPtr pidl);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cch);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cch);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cch);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
    void GetHotkey(out short pwHotkey);
    void SetHotkey(short wHotkey);
    void GetShowCmd(out int piShowCmd);
    void SetShowCmd(int iShowCmd);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cch, out int piIcon);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, int dwReserved);
    void Resolve(IntPtr hwnd, int fFlags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
}

[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
interface IPropertyStore
{
    void GetCount(out uint cProps);
    void GetAt(uint iProp, out PROPERTYKEY pkey);
    void GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
    void SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
    void Commit();
}

[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("0000010b-0000-0000-C000-000000000046")]
interface IPersistFile
{
    void GetClassID(out Guid pClassID);
    void IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, bool fRemember);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
    void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
}

[StructLayout(LayoutKind.Sequential, Pack = 4)]
struct PROPERTYKEY
{
    public Guid fmtid;
    public uint pid;
}

[StructLayout(LayoutKind.Explicit)]
struct PROPVARIANT
{
    [FieldOffset(0)] public ushort vt;
    [FieldOffset(8)] public IntPtr pointerValue;

    public static PROPVARIANT FromString(string value)
    {
        var pv = new PROPVARIANT();
        pv.vt = 31; // VT_LPWSTR
        pv.pointerValue = Marshal.StringToCoTaskMemUni(value);
        return pv;
    }

    public void Clear()
    {
        if (pointerValue != IntPtr.Zero)
        {
            Marshal.FreeCoTaskMem(pointerValue);
            pointerValue = IntPtr.Zero;
        }
    }
}

public static class HighdeasShortcutWriter
{
    public static void Write(string shortcutPath, string targetPath, string arguments,
                             string workingDir, string iconPath, string appId, string displayName)
    {
        // All three keys share PKEY_AppUserModel_* fmtid; pid 5 = ID, 4 = RelaunchDisplayName,
        // 3 = RelaunchIconResource. The ID is what merges the window into the pinned button;
        // the relaunch keys keep the name/icon correct even if the live window is pinned.
        var fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
        var appIdKey = new PROPERTYKEY { fmtid = fmtid, pid = 5 };
        var relaunchDisplayNameKey = new PROPERTYKEY { fmtid = fmtid, pid = 4 };
        var relaunchIconResourceKey = new PROPERTYKEY { fmtid = fmtid, pid = 3 };

        var link = (IShellLinkW)new CShellLink();
        link.SetPath(targetPath);
        link.SetArguments(arguments);
        link.SetWorkingDirectory(workingDir);
        link.SetIconLocation(iconPath, 0);
        link.SetDescription(displayName);

        var store = (IPropertyStore)link;
        var persist = (IPersistFile)link;

        var appIdVar = PROPVARIANT.FromString(appId);
        var displayVar = PROPVARIANT.FromString(displayName);
        var iconVar = PROPVARIANT.FromString(iconPath + ",0");

        try
        {
            store.SetValue(ref appIdKey, ref appIdVar);
            store.SetValue(ref relaunchDisplayNameKey, ref displayVar);
            store.SetValue(ref relaunchIconResourceKey, ref iconVar);
            store.Commit();
            persist.Save(shortcutPath, true);
        }
        finally
        {
            appIdVar.Clear();
            displayVar.Clear();
            iconVar.Clear();
        }
    }
}
"@

Remove-Item -LiteralPath $ShortcutPath -Force -ErrorAction SilentlyContinue
[HighdeasShortcutWriter]::Write($ShortcutPath, $Pythonw, ('"' + $Script + '"'), $Root, $Icon, $AppUserModelId, 'Highdeas')

Write-Host "Created shortcut: $ShortcutPath"
Write-Host "  Target : $Pythonw"
Write-Host "  Args   : `"$Script`""
Write-Host "  AppID  : $AppUserModelId"
