param(
    [string]$Version = "dev",
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
    $Global:PSNativeCommandUseErrorActionPreference = $false
}

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$DistDir = Join-Path $Root "dist\RestreamControl"
$ReleaseDir = Join-Path $Root "release"
$ZipPath = Join-Path $ReleaseDir "RestreamControl-$Version.zip"

Set-Location $Root

Write-Host "Checking build dependencies..."
$OldErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
py -m PyInstaller --version *> $null
$PyInstallerCheckExit = $LASTEXITCODE
$ErrorActionPreference = $OldErrorActionPreference
if ($PyInstallerCheckExit -ne 0) {
    Write-Host "Installing build dependencies from requirements-build.txt..."
    py -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install build dependencies."
    }
}

Write-Host "Cleaning old build output..."
if (Test-Path (Join-Path $Root "build")) {
    Remove-Item -LiteralPath (Join-Path $Root "build") -Recurse -Force
}
if (Test-Path $DistDir) {
    Remove-Item -LiteralPath $DistDir -Recurse -Force
}

Write-Host "Building Restream Control.exe..."
py -m PyInstaller --noconfirm RestreamControl.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

if (!(Test-Path $DistDir)) {
    throw "PyInstaller did not create $DistDir"
}

Write-Host "Copying release assets..."
$copies = @(
    @{ Source = "obs-template"; Destination = "obs-template" },
    @{ Source = "data"; Destination = "data" },
    @{ Source = "app\assets"; Destination = "assets" },
    @{ Source = "README.md"; Destination = "README.md" },
    @{ Source = "README_SETUP.md"; Destination = "README_SETUP.md" },
    @{ Source = "requirements.txt"; Destination = "requirements.txt" },
    @{ Source = "app\capture_runner_screenshots.ps1"; Destination = "capture_runner_screenshots.ps1" },
    @{ Source = "app\create_desktop_shortcut.ps1"; Destination = "create_desktop_shortcut.ps1" }
)

foreach ($copy in $copies) {
    $src = Join-Path $Root $copy.Source
    $dst = Join-Path $DistDir $copy.Destination
    if (Test-Path $dst) {
        Remove-Item -LiteralPath $dst -Recurse -Force
    }
    Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
}

foreach ($folder in @("obs_text", "crop_screenshots", "sync_screenshots", "state")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $DistDir $folder) | Out-Null
}

if (!$SkipZip) {
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
    if (Test-Path $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }
    Write-Host "Creating $ZipPath..."
    Compress-Archive -Path (Join-Path $DistDir "*") -DestinationPath $ZipPath -Force
}

Write-Host ""
Write-Host "Build complete:"
Write-Host "  $DistDir"
if (!$SkipZip) {
    Write-Host "  $ZipPath"
}
