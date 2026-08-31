param(
    [ValidateSet("Install", "Restore")]
    [string]$Mode = "Install",
    [Parameter(Mandatory = $true)]
    [int]$CurrentPid,
    [Parameter(Mandatory = $true)]
    [string]$InstallDir,
    [Parameter(Mandatory = $true)]
    [string]$SourceDir,
    [Parameter(Mandatory = $true)]
    [string]$BackupRoot,
    [Parameter(Mandatory = $true)]
    [string]$HealthFile,
    [Parameter(Mandatory = $true)]
    [string]$HealthToken,
    [Parameter(Mandatory = $true)]
    [string]$ResultFile,
    [string]$TargetVersion = "unknown",
    [int]$HealthTimeoutSeconds = 30
)

$ErrorActionPreference = "Stop"
$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$SourceDir = [IO.Path]::GetFullPath($SourceDir).TrimEnd('\')
$BackupRoot = [IO.Path]::GetFullPath($BackupRoot).TrimEnd('\')
$InstallParent = Split-Path -Parent $InstallDir
$InstallName = Split-Path -Leaf $InstallDir
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$TemporaryBackup = Join-Path $InstallParent ".$InstallName.update-backup-$Stamp"
$FailedInstall = Join-Path $InstallParent ".$InstallName.failed-update-$Stamp"
$FinalBackup = Join-Path $BackupRoot "$Stamp-$TargetVersion"
$NewProcess = $null

function Write-Result([string]$Status, [string]$Message, [string]$Backup = "") {
    $parent = Split-Path -Parent $ResultFile
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    @{ status = $Status; mode = $Mode; message = $Message; backup = $Backup; version = $TargetVersion; timestamp = (Get-Date).ToString("o") } |
        ConvertTo-Json | Set-Content -LiteralPath $ResultFile -Encoding UTF8
}

function Wait-ForExit([int]$PidToWait) {
    for ($i = 0; $i -lt 120; $i++) {
        if (!(Get-Process -Id $PidToWait -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "Restream Control did not close within 60 seconds."
}

function Copy-Application([string]$From, [string]$To) {
    if (!(Test-Path -LiteralPath (Join-Path $From "Restream Control.exe"))) {
        throw "Source application is missing Restream Control.exe."
    }
    New-Item -ItemType Directory -Force -Path $To | Out-Null
    Get-ChildItem -LiteralPath $From -Force | Copy-Item -Destination $To -Recurse -Force
}

function Start-And-Verify([string]$ApplicationDir) {
    if (Test-Path -LiteralPath $HealthFile) { Remove-Item -LiteralPath $HealthFile -Force }
    $exe = Join-Path $ApplicationDir "Restream Control.exe"
    $healthArg = '"' + $HealthFile.Replace('"', '\"') + '"'
    $tokenArg = '"' + $HealthToken.Replace('"', '\"') + '"'
    $script:NewProcess = Start-Process -FilePath $exe -WorkingDirectory $ApplicationDir -ArgumentList @(
        "--update-health-file", $healthArg,
        "--update-health-token", $tokenArg
    ) -PassThru
    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $HealthFile) {
            try {
                $health = Get-Content -LiteralPath $HealthFile -Raw | ConvertFrom-Json
                if ($health.token -eq $HealthToken) { return $true }
            } catch { }
        }
        if ($script:NewProcess.HasExited) { return $false }
        Start-Sleep -Milliseconds 500
        $script:NewProcess.Refresh()
    }
    return $false
}

try {
    Wait-ForExit $CurrentPid
    if (!(Test-Path -LiteralPath $InstallDir)) { throw "Installation folder was not found: $InstallDir" }
    if (Test-Path -LiteralPath $TemporaryBackup) { Remove-Item -LiteralPath $TemporaryBackup -Recurse -Force }

    Move-Item -LiteralPath $InstallDir -Destination $TemporaryBackup
    try {
        Copy-Application $SourceDir $InstallDir
        if (!(Start-And-Verify $InstallDir)) { throw "The updated application did not confirm a healthy startup." }

        New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
        if (Test-Path -LiteralPath $FinalBackup) { Remove-Item -LiteralPath $FinalBackup -Recurse -Force }
        Move-Item -LiteralPath $TemporaryBackup -Destination $FinalBackup
        Write-Result "success" "$Mode completed and Restream Control restarted successfully." $FinalBackup
        if ($Mode -eq "Install") {
            if (Test-Path -LiteralPath $SourceDir) { Remove-Item -LiteralPath $SourceDir -Recurse -Force -ErrorAction SilentlyContinue }
            Remove-Item -LiteralPath (Join-Path (Split-Path -Parent $SourceDir) "update.zip") -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath (Join-Path (Split-Path -Parent $SourceDir) "update.zip.sha256") -Force -ErrorAction SilentlyContinue
        }
        exit 0
    } catch {
        if ($NewProcess -and !$NewProcess.HasExited) { Stop-Process -Id $NewProcess.Id -Force -ErrorAction SilentlyContinue }
        if (Test-Path -LiteralPath $InstallDir) { Move-Item -LiteralPath $InstallDir -Destination $FailedInstall }
        Move-Item -LiteralPath $TemporaryBackup -Destination $InstallDir
        $rollbackExe = Join-Path $InstallDir "Restream Control.exe"
        if (Test-Path -LiteralPath $rollbackExe) { Start-Process -FilePath $rollbackExe -WorkingDirectory $InstallDir }
        Write-Result "rolled_back" "Update failed and the previous version was restored: $($_.Exception.Message)" $InstallDir
        exit 2
    }
} catch {
    Write-Result "failed" "$Mode could not start: $($_.Exception.Message)"
    exit 1
}
