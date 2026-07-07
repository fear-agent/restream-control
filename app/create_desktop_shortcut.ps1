param(
    [string]$ShortcutName = "Restream Control",
    [ValidateSet("Desktop", "StartMenu")]
    [string]$Location = "Desktop"
)

$ErrorActionPreference = "Stop"

$AppDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppScript = Join-Path $AppDir "restream_app.py"
$BatchLauncher = Join-Path $AppDir "start_restream_app.bat"
if ($Location -eq "StartMenu") {
    $ShortcutDir = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"
} else {
    $ShortcutDir = [Environment]::GetFolderPath("Desktop")
}
$ShortcutPath = Join-Path $ShortcutDir ($ShortcutName + ".lnk")

$Pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
if ($Pythonw) {
    $Shortcut.TargetPath = $Pythonw
    $Shortcut.Arguments = '"' + $AppScript + '"'
} else {
    $Shortcut.TargetPath = $BatchLauncher
    $Shortcut.Arguments = ""
}
$Shortcut.WorkingDirectory = $AppDir
$Shortcut.Description = "Launch Restream Control"
$Shortcut.WindowStyle = 7
$Shortcut.Save()

Write-Host "Created shortcut: $ShortcutPath"
