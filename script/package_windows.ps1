param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ReleaseDir = Join-Path $Root "release\windows"
$ZipPath = Join-Path $ReleaseDir "PDM-windows-x64.zip"
$ChecksumPath = Join-Path $ReleaseDir "checksums.txt"

Set-Location $Root

& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt pyinstaller
& $Python -m PyInstaller --noconfirm --clean build.spec

New-Item -ItemType Directory -Force $ReleaseDir | Out-Null
if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

Compress-Archive -Path (Join-Path $Root "dist\PDM\*") -DestinationPath $ZipPath
$Hash = Get-FileHash -Algorithm SHA256 $ZipPath
"$($Hash.Hash.ToLower())  $(Split-Path -Leaf $ZipPath)" | Set-Content -Encoding UTF8 $ChecksumPath

Write-Host $ZipPath
