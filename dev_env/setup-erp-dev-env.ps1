<#
Cross-Platform Developer Environment Setup
------------------------------------------
Installs recommended developer workstation tools on macOS and Windows.

This is a lightweight bootstrap script: it detects the platform, installs
missing tools (using Homebrew on macOS or silent installers on Windows), and
installs a small set of useful VS Code extensions.

Run this script from PowerShell (Windows) or pwsh (macOS):

  pwsh ./dev_env/setup-erp-dev-env.ps1

#>

Write-Host "=== Developer Environment Setup (Cross-Platform) ===" -ForegroundColor Cyan

# Detect OS
$IsMacOS = $false
$IsWindows = $false

if ($PSVersionTable.PSPlatform -eq 'Unix') {
    # PowerShell Core on macOS/Linux identifies as Unix platform
    if ($PSVersionTable.OS -match 'Darwin') { $IsMacOS = $true }
} elseif ($PSVersionTable.OS -match 'Windows') {
    $IsWindows = $true
}

Write-Host "Detected OS: $($PSVersionTable.OS)" -ForegroundColor Yellow

# Helper: Check if a command exists
function Test-Command {
    param([string]$cmd)
    return (Get-Command $cmd -ErrorAction SilentlyContinue) -ne $null
}

# Helper: Download file
function Download-File {
    param(
        [Parameter(Mandatory=$true)][string]$Url,
        [Parameter(Mandatory=$true)][string]$OutFile
    )
    Write-Host "Downloading $Url -> $OutFile"
    Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
}

# -------------------------------
# macOS Setup (Homebrew)
# -------------------------------
if ($IsMacOS) {
    Write-Host "`n=== macOS Setup ===" -ForegroundColor Cyan

    if (-not (Test-Command 'brew')) {
        Write-Host 'Homebrew not found. Installing Homebrew...' -ForegroundColor Yellow
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    } else {
        Write-Host 'OK Homebrew found.' -ForegroundColor Green
    }

    $macPackages = @('git')
    foreach ($pkg in $macPackages) {
        if (-not (Test-Command $pkg)) {
            Write-Host "Installing $pkg..."
            brew install $pkg
        } else { Write-Host "OK $pkg already installed." -ForegroundColor Green }
    }

    # GUI casks
    $casks = @('visual-studio-code', 'github', 'podman-desktop')
    foreach ($c in $casks) {
        Write-Host "Ensuring cask: $c"
        try {
            brew install --cask $c
        } catch {
            Write-Host "(cask $c may already be installed or install failed)"
        }
    }

    Write-Host "`nInstalling VS Code Remote Tools..." -ForegroundColor Yellow
    $extensions = @(
        'ms-vscode-remote.vscode-remote-extensionpack',
        'ms-vscode-remote.remote-containers',
        'ms-vscode-remote.remote-ssh',
        'vscjava.vscode-java-pack'
    )
    if (Test-Command 'code') {
        $installed = code --list-extensions
        foreach ($ext in $extensions) {
            if ($installed -contains $ext) { Write-Host "OK $ext already installed." -ForegroundColor Green }
            else { Write-Host "Installing $ext..."; code --install-extension $ext }
        }
    } else { Write-Host 'VS Code CLI not available (code), skipping extension install.' -ForegroundColor Yellow }

    Write-Host "`nmacOS setup complete!" -ForegroundColor Cyan
    exit 0
}

# -------------------------------
# Windows Setup
# -------------------------------
if ($IsWindows) {
    Write-Host "`n=== Windows Setup ===" -ForegroundColor Cyan

    $TempDir = Join-Path $env:TEMP 'devtools'
    New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

    # Git
    if (-not (Test-Command 'git')) {
        Write-Host 'Installing Git for Windows...'
        $gitInstaller = Join-Path $TempDir 'Git-64-bit.exe'
        Download-File 'https://github.com/git-for-windows/git/releases/latest/download/Git-64-bit.exe' $gitInstaller
        Start-Process -FilePath $gitInstaller -ArgumentList '/VERYSILENT' -Wait
    } else { Write-Host 'OK Git already installed.' -ForegroundColor Green }

    # GitHub Desktop
    if (-not (Test-Command 'github')) {
        Write-Host 'Installing GitHub Desktop...'
        $ghdInstaller = Join-Path $TempDir 'github-desktop.exe'
        Download-File 'https://central.github.com/deployments/desktop/desktop/latest/win32' $ghdInstaller
        Start-Process -FilePath $ghdInstaller -ArgumentList '/SILENT' -Wait
    } else { Write-Host 'OK GitHub Desktop already installed.' -ForegroundColor Green }

    # VS Code
    if (-not (Test-Command 'code')) {
        Write-Host 'Installing Visual Studio Code...'
        $vscodeInstaller = Join-Path $TempDir 'vscode.exe'
        Download-File 'https://update.code.visualstudio.com/latest/win32-x64-user/stable' $vscodeInstaller
        Start-Process -FilePath $vscodeInstaller -ArgumentList '/VERYSILENT' -Wait
    } else { Write-Host 'OK VS Code already installed.' -ForegroundColor Green }

    # Podman Desktop
    if (-not (Test-Command 'podman')) {
        Write-Host 'Installing Podman Desktop...'
        $podmanInstaller = Join-Path $TempDir 'podman-desktop.msi'
        Download-File 'https://github.com/containers/podman-desktop/releases/latest/download/podman-desktop-setup-x64.msi' $podmanInstaller
        Start-Process -FilePath 'msiexec.exe' -ArgumentList "/i `"$podmanInstaller`" /qn" -Wait
    } else { Write-Host 'OK Podman Desktop already installed.' -ForegroundColor Green }

    # Notepad++ (optional)
    if (-not (Test-Command 'notepad++')) {
        Write-Host 'Installing Notepad++...'
        $npInstaller = Join-Path $TempDir 'npp.exe'
        Download-File 'https://github.com/notepad-plus-plus/notepad-plus-plus/releases/latest/download/npp.8.6.2.Installer.x64.exe' $npInstaller
        Start-Process -FilePath $npInstaller -ArgumentList '/S' -Wait
    } else { Write-Host 'OK Notepad++ already installed.' -ForegroundColor Green }

    Write-Host "`nInstalling VS Code Remote Tools..." -ForegroundColor Yellow
    $extensions = @(
        'ms-vscode-remote.vscode-remote-extensionpack',
        'ms-vscode-remote.remote-containers',
        'ms-vscode-remote.remote-ssh',
        'vscjava.vscode-java-pack'
    )
    if (Test-Command 'code') {
        $installed = code --list-extensions
        foreach ($ext in $extensions) {
            if ($installed -contains $ext) { Write-Host "OK $ext already installed." -ForegroundColor Green }
            else { Write-Host "Installing $ext..."; code --install-extension $ext }
        }
    } else { Write-Host 'VS Code CLI not available (code), skipping extension install.' -ForegroundColor Yellow }

    Write-Host "`nWindows setup complete!" -ForegroundColor Cyan
}

