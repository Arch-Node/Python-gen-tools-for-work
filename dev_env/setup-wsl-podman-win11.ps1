<#
PowerShell setup script for Windows 11 to check and install WSL 2 and Podman.

Usage:
  pwsh .\dev_env\setup-wsl-podman-win11.ps1

This script performs the following checks and actions:
  - verifies administrator privileges
  - checks Windows 11 / WSL 2 compatibility
  - enables WSL and Virtual Machine Platform features
  - installs the default Ubuntu WSL distro if missing
  - converts Ubuntu to WSL 2 if it is still on version 1
  - installs Podman Desktop if missing
  - installs Podman inside Ubuntu WSL
  - configures Podman registries and rootless storage if possible
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest

function Assert-Admin {
    if (-not ([bool](net session 2>$null))) {
        Write-Error 'This script must be run as Administrator.'
        exit 1
    }
}

function Test-Command {
    param([string]$Command)
    return (Get-Command $Command -ErrorAction SilentlyContinue) -ne $null
}

function Download-File {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [Parameter(Mandatory=$true)][string]$OutFile
    )
    Write-Host "Downloading $Url to $OutFile"
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
}

function Get-FeatureState {
    param([string]$FeatureName)
    $feature = Get-WindowsOptionalFeature -Online -FeatureName $FeatureName -ErrorAction SilentlyContinue
    return if ($feature) { $feature.State } else { 'Disabled' }
}

function Enable-FeatureIfNeeded {
    param([string]$FeatureName, [string]$Description)
    $state = Get-FeatureState -FeatureName $FeatureName
    if ($state -eq 'Enabled') {
        Write-Host "OK: $Description is already enabled." -ForegroundColor Green
        return $false
    }

    Write-Host "Enabling $Description..." -ForegroundColor Yellow
    Enable-WindowsOptionalFeature -Online -FeatureName $FeatureName -NoRestart -All | Out-Null
    return $true
}

function Get-WslVersion {
    try {
        $output = & wsl.exe --version 2>&1
        $match = $output | Select-String -Pattern 'WSL version:\s*(\d+)' -AllMatches
        if ($match) {
            return [int]$match.Matches[0].Groups[1].Value
        }
    } catch {
        return 0
    }
    return 0
}

function Ensure-WslDistro {
    param([string]$DistroName)

    $installed = & wsl.exe --list --quiet 2>$null | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
    if ($installed -contains $DistroName) {
        Write-Host "OK: WSL distro '$DistroName' is installed." -ForegroundColor Green
        return $true
    }

    Write-Host "Installing WSL distro '$DistroName'..." -ForegroundColor Cyan
    & wsl.exe --install -d $DistroName
    return $false
}

function Ensure-DistroVersion2 {
    param([string]$DistroName)

    $list = & wsl.exe -l -v 2>$null | Select-Object -Skip 1
    foreach ($line in $list) {
        if ($line -match "^\s*$DistroName\s+\S+\s+(\d+)") {
            $version = [int]$Matches[1]
            if ($version -eq 1) {
                Write-Host "Converting distro '$DistroName' to WSL 2..." -ForegroundColor Yellow
                & wsl.exe --set-version $DistroName 2 | Out-Null
                Write-Host "Distro '$DistroName' is now WSL 2." -ForegroundColor Green
            } elseif ($version -eq 2) {
                Write-Host "Distro '$DistroName' is already WSL 2." -ForegroundColor Green
            }
            return
        }
    }
    Write-Warning "Unable to determine WSL version for distro '$DistroName'."
}

function Install-PodmanDesktop {
    param([string]$TempDir)
    $installer = Join-Path $TempDir 'podman-desktop-setup-x64.msi'

    if (Test-Command 'podman') {
        Write-Host 'OK: Podman CLI is already available.' -ForegroundColor Green
        return
    }

    if (Test-Command 'winget') {
        Write-Host 'Installing Podman Desktop using winget...' -ForegroundColor Cyan
        & winget install --silent --accept-package-agreements --accept-source-agreements RedHat.Podman-Desktop | Out-Null
        if (Test-Command 'podman') {
            Write-Host 'Podman Desktop installed successfully.' -ForegroundColor Green
            return
        }
    }

    Write-Host 'Installing Podman Desktop via MSI...' -ForegroundColor Cyan
    Download-File 'https://github.com/containers/podman-desktop/releases/latest/download/podman-desktop-setup-x64.msi' $installer
    Start-Process -FilePath 'msiexec.exe' -ArgumentList "/i `"$installer`" /qn /norestart" -Wait -NoNewWindow
    if (Test-Command 'podman') {
        Write-Host 'Podman Desktop installed successfully.' -ForegroundColor Green
    } else {
        Write-Warning 'Podman Desktop installed, but podman is not in PATH yet. Please restart your shell or sign out/in.'
    }
}

function Install-PodmanInWsl {
    param([string]$DistroName)

    try {
        Write-Host "Installing Podman inside WSL distro '$DistroName'..." -ForegroundColor Cyan
        & wsl.exe -d $DistroName -- bash -lc "sudo apt-get update && sudo apt-get install -y podman fuse-overlayfs && podman --version"
        Write-Host "Podman installation inside WSL distro '$DistroName' completed." -ForegroundColor Green
    } catch {
        Write-Warning "Unable to install Podman inside WSL distro '$DistroName' automatically. Launch the distro once and rerun this script or install inside WSL manually."
    }
}

function Configure-PodmanStorage {
    param([string]$DistroName)

    Write-Host "Configuring Podman storage and registries inside '$DistroName'..." -ForegroundColor Cyan
    $script = @'
mkdir -p ~/.config/containers
cat > ~/.config/containers/storage.conf <<'EOF'
[storage]
driver = "overlay"
graphroot = "/home/$USER/.local/share/containers/storage"
runroot = "/run/user/$UID/containers"

[storage.options.overlay]
mount_program = "/usr/bin/fuse-overlayfs"
EOF

sudo mkdir -p /etc/containers
sudo tee /etc/containers/registries.conf > /dev/null <<'EOF'
# Search these registries when no registry is specified in the image name
unqualified-search-registries = ["docker.io", "quay.io", "ghcr.io"]

[[registry]]
prefix = "docker.io"
location = "docker.io"
EOF
'

    try {
        & wsl.exe -d $DistroName -- bash -lc $script
        Write-Host "Podman storage/registry configuration applied." -ForegroundColor Green
    } catch {
        Write-Warning "Failed to configure Podman storage/registries inside '$DistroName'. You may need to run the commands manually."    }
}

Assert-Admin

Write-Host '=== Windows 11 WSL + Podman Setup ===' -ForegroundColor Cyan

$osInfo = Get-CimInstance -ClassName Win32_OperatingSystem
$version = [version]$osInfo.Version
if ($version.Major -lt 10 -or ($version.Major -eq 10 -and $version.Build -lt 22000)) {
    Write-Error "Windows 11 is required. Detected Windows version $($osInfo.Version)."
    exit 1
}

$changed = $false
$changed += Enable-FeatureIfNeeded -FeatureName 'Microsoft-Windows-Subsystem-Linux' -Description 'Windows Subsystem for Linux'
$changed += Enable-FeatureIfNeeded -FeatureName 'VirtualMachinePlatform' -Description 'Virtual Machine Platform'

if ($changed) {
    Write-Host '`nA restart is required to complete WSL feature installation.' -ForegroundColor Yellow
    Write-Host 'Please restart Windows and rerun this script after reboot.'
    exit 0
}

if (-not (Test-Command 'wsl.exe')) {
    Write-Error 'wsl.exe is not available after feature enablement. Please reboot and rerun this script.'
    exit 1
}

$wslVersion = Get-WslVersion
if ($wslVersion -lt 2) {
    Write-Host 'Setting WSL default version to 2...' -ForegroundColor Cyan
    & wsl.exe --set-default-version 2 | Out-Null
    $wslVersion = Get-WslVersion
}

if ($wslVersion -lt 2) {
    Write-Warning 'WSL version did not report as 2. Run "wsl --update" and restart the shell, then rerun this script.'
    exit 1
}

Write-Host "WSL version is $wslVersion." -ForegroundColor Green

$defaultDistro = 'Ubuntu'
$distroInstalled = Ensure-WslDistro -DistroName $defaultDistro

if ($distroInstalled) {
    Ensure-DistroVersion2 -DistroName $defaultDistro
}

Write-Host '`nChecking Podman Desktop / CLI...' -ForegroundColor Cyan
$TempDir = Join-Path $env:TEMP 'wsl-podman-setup'
New-Item -ItemType Directory -Force -Path $TempDir | Out-Null
Install-PodmanDesktop -TempDir $TempDir

if ($distroInstalled) {
    Write-Host '`nInstalling Podman inside WSL distro...' -ForegroundColor Cyan
    Install-PodmanInWsl -DistroName $defaultDistro
    Configure-PodmanStorage -DistroName $defaultDistro
    Write-Host '`nVerifying Podman inside WSL...'
    & wsl.exe -d $defaultDistro -- bash -lc "podman info --format '{{.Host.OCIRuntime.Name}} {{.Host.OCIRuntime.Version}}'" | Write-Host
} else {
    Write-Host "`nWSL distro '$defaultDistro' was installed. Launch it once to complete first-time initialization, then rerun this script to install Podman and configure storage." -ForegroundColor Yellow
}

Write-Host '`nSetup complete. Restart your shell or sign out/in if Podman Desktop was installed.' -ForegroundColor Cyan
