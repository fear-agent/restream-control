param(
    [string]$PackageDir = "",
    [string]$ReleaseZip = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
if (!$PackageDir) { $PackageDir = Join-Path $Root "dist\RestreamControl" }
if (!$ReleaseZip) { $ReleaseZip = Join-Path $Root "release\RestreamControl-v0.3.0.zip" }
$PackageDir = [IO.Path]::GetFullPath($PackageDir)
$ReleaseZip = [IO.Path]::GetFullPath($ReleaseZip)
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ("RestreamControl-UpdaterTest-" + [guid]::NewGuid().ToString("N"))

function Wait-ForFile([string]$Path, [int]$Seconds = 35) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $Path) { return }
        Start-Sleep -Milliseconds 300
    }
    throw "Timed out waiting for $Path"
}

function Stop-TestApps {
    Get-CimInstance Win32_Process -Filter "Name = 'Restream Control.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($TestRoot, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Start-OldApp([string]$Install, [string]$Data) {
    $previous = $env:RESTREAM_CONTROL_DATA_DIR
    $env:RESTREAM_CONTROL_DATA_DIR = $Data
    try {
        return Start-Process -FilePath (Join-Path $Install "Restream Control.exe") -WorkingDirectory $Install -WindowStyle Hidden -PassThru
    } finally {
        $env:RESTREAM_CONTROL_DATA_DIR = $previous
    }
}

function Invoke-Helper([string]$Helper, [int]$OldPid, [string]$Install, [string]$Source, [string]$Data, [string]$Name, [string]$Mode = "Install") {
    $health = Join-Path $Data "$Name-health.json"
    $result = Join-Path $Data "$Name-result.json"
    $backup = Join-Path $Data "backups"
    $token = [guid]::NewGuid().ToString("N")
    $previous = $env:RESTREAM_CONTROL_DATA_DIR
    $env:RESTREAM_CONTROL_DATA_DIR = $Data
    try {
        $process = Start-Process powershell.exe -WindowStyle Hidden -PassThru -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $Helper + '"'),
            "-Mode", $Mode, "-CurrentPid", $OldPid,
            "-InstallDir", ('"' + $Install + '"'), "-SourceDir", ('"' + $Source + '"'),
            "-BackupRoot", ('"' + $backup + '"'), "-HealthFile", ('"' + $health + '"'),
            "-HealthToken", $token, "-ResultFile", ('"' + $result + '"'),
            "-TargetVersion", "test", "-HealthTimeoutSeconds", "8"
        )
        Start-Sleep -Milliseconds 800
        Stop-Process -Id $OldPid -Force
        Wait-Process -Id $process.Id -Timeout 30
    } finally {
        $env:RESTREAM_CONTROL_DATA_DIR = $previous
    }
    Wait-ForFile $result 5
    return Get-Content -LiteralPath $result -Raw | ConvertFrom-Json
}

try {
    New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null

    $checksumFile = "$ReleaseZip.sha256"
    $expected = (Get-Content -LiteralPath $checksumFile -Raw).Substring(0, 64).ToLowerInvariant()
    $actual = (Get-FileHash -LiteralPath $ReleaseZip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expected -ne $actual) { throw "Release checksum does not match the ZIP." }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($ReleaseZip)
    try {
        $names = @($archive.Entries | ForEach-Object FullName)
        if ("apply_update.ps1" -notin $names) { throw "Release ZIP is missing apply_update.ps1." }
        if ($names -match '(^|/)runners\.csv$') { throw "Release ZIP contains a personal runners.csv." }
    } finally {
        $archive.Dispose()
    }

    $successRoot = Join-Path $TestRoot "success"
    $successInstall = Join-Path $successRoot "RestreamControl"
    $successSource = Join-Path $successRoot "staged"
    $successData = Join-Path $successRoot "data"
    Copy-Item -LiteralPath $PackageDir -Destination $successInstall -Recurse
    Copy-Item -LiteralPath $PackageDir -Destination $successSource -Recurse
    Set-Content -LiteralPath (Join-Path $successInstall "old-marker.txt") -Value "old"
    Set-Content -LiteralPath (Join-Path $successSource "new-marker.txt") -Value "new"
    $helper = Join-Path $successRoot "apply_update.ps1"
    Copy-Item -LiteralPath (Join-Path $PackageDir "apply_update.ps1") -Destination $helper
    $old = Start-OldApp $successInstall $successData
    $success = Invoke-Helper $helper $old.Id $successInstall $successSource $successData "success"
    if ($success.status -ne "success") { throw "Healthy update failed: $($success.message)" }
    if (!(Test-Path -LiteralPath (Join-Path $successInstall "new-marker.txt"))) { throw "New application files were not installed." }
    if (!(Test-Path -LiteralPath (Join-Path $success.backup "old-marker.txt"))) { throw "Previous version backup was not retained." }

    Stop-TestApps
    $old = Start-OldApp $successInstall $successData
    $restore = Invoke-Helper $helper $old.Id $successInstall $success.backup $successData "restore" "Restore"
    if ($restore.status -ne "success") { throw "Manual restore failed: $($restore.message)" }
    if (!(Test-Path -LiteralPath (Join-Path $successInstall "old-marker.txt"))) { throw "Restore did not install the previous application files." }
    if (Test-Path -LiteralPath (Join-Path $successInstall "new-marker.txt")) { throw "Restore left files from the newer application behind." }

    Stop-TestApps
    $rollbackRoot = Join-Path $TestRoot "rollback"
    $rollbackInstall = Join-Path $rollbackRoot "RestreamControl"
    $rollbackSource = Join-Path $rollbackRoot "invalid-staged"
    $rollbackData = Join-Path $rollbackRoot "data"
    Copy-Item -LiteralPath $PackageDir -Destination $rollbackInstall -Recurse
    New-Item -ItemType Directory -Force -Path $rollbackSource | Out-Null
    Set-Content -LiteralPath (Join-Path $rollbackInstall "old-marker.txt") -Value "old"
    Set-Content -LiteralPath (Join-Path $rollbackSource "Restream Control.exe") -Value "invalid executable"
    $rollbackHelper = Join-Path $rollbackRoot "apply_update.ps1"
    Copy-Item -LiteralPath (Join-Path $PackageDir "apply_update.ps1") -Destination $rollbackHelper
    $old = Start-OldApp $rollbackInstall $rollbackData
    $rollback = Invoke-Helper $rollbackHelper $old.Id $rollbackInstall $rollbackSource $rollbackData "rollback"
    if ($rollback.status -ne "rolled_back") { throw "Failed update did not roll back: $($rollback.message)" }
    if (!(Test-Path -LiteralPath (Join-Path $rollbackInstall "old-marker.txt"))) { throw "Previous application was not restored." }

    Write-Host "Packaged updater success path: OK"
    Write-Host "Packaged updater manual restore path: OK"
    Write-Host "Packaged updater rollback path: OK"
    Write-Host "Release checksum and contents: OK"
} finally {
    Stop-TestApps
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    $resolvedTestRoot = [IO.Path]::GetFullPath($TestRoot)
    if ($resolvedTestRoot.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and $resolvedTestRoot -like "*RestreamControl-UpdaterTest-*") {
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
