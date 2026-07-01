param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\ffmpeg",
    [switch]$Force,
    [switch]$SkipPathUpdate,
    [switch]$OpenNewTerminal
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[ffmpeg-install] $Message"
}

function Update-UserAndSessionPath {
    param([string]$BinPath)

    Write-Info "Updating user PATH..."
    $currentUserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $pathParts = @()
    if ($currentUserPath) {
        $pathParts = $currentUserPath.Split(';') | Where-Object { $_ }
    }

    $alreadySet = $pathParts | Where-Object { $_.TrimEnd('\\') -ieq $BinPath.TrimEnd('\\') }
    if (-not $alreadySet) {
        $newUserPath = if ($currentUserPath) {
            "$currentUserPath;$BinPath"
        } else {
            $BinPath
        }
        [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
        Write-Info "Added to user PATH: $BinPath"
    } else {
        Write-Info "User PATH already contains: $BinPath"
    }

    if (-not ($env:Path.Split(';') | Where-Object { $_.TrimEnd('\\') -ieq $BinPath.TrimEnd('\\') })) {
        $env:Path = "$BinPath;$env:Path"
        Write-Info "Added to current session PATH."
    }
}

function Open-FFmpegTerminal {
    param([string]$BinPath)

    if (-not $OpenNewTerminal) {
        return
    }

    $ffmpegCmd = Join-Path $BinPath "ffmpeg.exe"
    if (-not (Test-Path $ffmpegCmd)) {
        Write-Info "Skipping terminal launch; ffmpeg.exe not found in $BinPath"
        return
    }

    Write-Info "Opening a new terminal with FFmpeg on PATH..."
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "& `"$ffmpegCmd`" -version"
    ) | Out-Null
}

if ($PSVersionTable.PSVersion.Major -lt 5) {
    throw "PowerShell 5.1 or newer is required."
}

$downloadPage = "https://ffmpeg.org/download.html#build-windows"
$releaseApi = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
$tempRoot = Join-Path $env:TEMP "ffmpeg-install"
$zipPath = Join-Path $tempRoot "ffmpeg-latest-win64.zip"
$extractPath = Join-Path $tempRoot "extract"
$installedBin = Join-Path $InstallRoot "bin"
$installedExe = Join-Path $installedBin "ffmpeg.exe"

Write-Info "Download source: $downloadPage"

# Pre-check before any download work.
if ((Test-Path $installedExe) -and -not $Force) {
    Write-Info "Existing FFmpeg install detected at: $InstallRoot"
    try {
        $versionLine = (& $installedExe -version 2>$null | Select-Object -First 1)
        if ($versionLine) {
            Write-Info "Installed version: $versionLine"
        }
    } catch {
        Write-Info "Installed version: (could not determine)"
    }

    if (-not $SkipPathUpdate) {
        Update-UserAndSessionPath -BinPath $installedBin
    }

    Write-Info "Nothing to download. Use -Force to reinstall."
    Write-Info "ffmpeg.exe location: $installedExe"
    Open-FFmpegTerminal -BinPath $installedBin
    return
}

if ((Test-Path $InstallRoot) -and -not $Force) {
    throw "Install location already exists: $InstallRoot. Use -Force to replace it."
}

Write-Info "Resolving latest Windows build from BtbN releases..."

if (Test-Path $tempRoot) {
    Remove-Item $tempRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $tempRoot | Out-Null

$release = Invoke-RestMethod -Uri $releaseApi
$asset = $release.assets |
    Where-Object { $_.name -like "*win64-gpl*.zip" -and $_.name -notlike "*shared*" } |
    Select-Object -First 1

if (-not $asset) {
    throw "Could not find a latest win64 GPL FFmpeg zip asset in release metadata."
}

Write-Info "Downloading: $($asset.name)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

Write-Info "Extracting package..."
Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force

$ffmpegExe = Get-ChildItem -Path $extractPath -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
if (-not $ffmpegExe) {
    throw "Downloaded archive did not contain ffmpeg.exe."
}

$binPath = Split-Path $ffmpegExe.FullName -Parent
$sourceRoot = Split-Path $binPath -Parent

if ((Test-Path $InstallRoot) -and -not $Force) {
    throw "Install location already exists: $InstallRoot. Re-run with -Force to replace it."
}

if (Test-Path $InstallRoot) {
    Write-Info "Removing existing install path: $InstallRoot"
    Remove-Item $InstallRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
Write-Info "Copying files to: $InstallRoot"
Copy-Item -Path (Join-Path $sourceRoot "*") -Destination $InstallRoot -Recurse -Force

if (-not (Test-Path (Join-Path $installedBin "ffmpeg.exe"))) {
    throw "Install completed but ffmpeg.exe was not found in $installedBin."
}

if (-not $SkipPathUpdate) {
    Update-UserAndSessionPath -BinPath $installedBin
}

Write-Info "Install complete."
Write-Info "ffmpeg.exe location: $(Join-Path $installedBin 'ffmpeg.exe')"
Write-Info "Open a new terminal window before running ffmpeg commands in other shells."
Open-FFmpegTerminal -BinPath $installedBin
