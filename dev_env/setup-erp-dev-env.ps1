<#
    Cross-Platform Developer Environment Setup
    ------------------------------------------
    Installs required tools on Windows and macOS:

    Windows:
      - Git
      - GitHub Desktop
      - VS Code
      - Podman Desktop
      - Notepad++
      - VS Code Remote Tools

    macOS:
      - Git (via Homebrew)
      - GitHub Desktop
      - VS Code
      - Podman Desktop
      - VS Code Remote Tools
#>

Write-Host "=== Developer Environment Setup (Cross-Platform) ===" -ForegroundColor Cyan

# Detect OS
$IsMacOS = $false
$IsWindows = $false

if ($PSVersionTable.OS -match "Darwin") {
    $IsMacOS = $true
} elseif ($PSVersionTable.OS -match "Windows") {
    $IsWindows = $true
}

Write-Host "Detected OS: $($PSVersionTable.OS)" -ForegroundColor Yellow

# Helper: Check if a command exists
function Test-Command {
    param([string]$cmd)
    $exists = Get-Command $cmd -ErrorAction SilentlyContinue
    return $exists -ne $null
}

# Helper: Download file
function Download-File {
    param(
        [string]$Url,
        [string]$OutFile
    )
    Write-Host "Downloading $Url..."
    Invoke-WebRequest -Uri $Url -OutFile $OutFile
}

# -------------------------------
# macOS Setup
# -------------------------------
if ($IsMacOS) {
    Write-Host "`n=== macOS Setup ===" -ForegroundColor Cyan

    # Homebrew
    if (-not (Test-Command "brew")) {
        Write-Host "❌ Homebrew not found. Installing Homebrew..." -ForegroundColor Yellow
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    } else {
        Write-Host "✔ Homebrew found." -ForegroundColor Green
    }

    # Git
    if (-not (Test-Command "git")) {
        Write-Host "Installing Git..."
        brew install git
    } else {
        Write-Host "✔ Git already installed." -ForegroundColor Green
    }

    # VS Code
    if (-not (Test-Command "code")) {
        Write-Host "Installing Visual Studio Code..."
        brew install --cask visual-studio-code
    } else {
        Write-Host "✔ VS Code already installed." -ForegroundColor Green
    }

    # GitHub Desktop
    if (-not (Test-Command "github")) {
        Write-Host "Installing GitHub Desktop..."
        brew install --cask github
    } else {
        Write-Host "✔ GitHub Desktop already installed." -ForegroundColor Green
    }

    # Podman Desktop
    if (-not (Test-Command "podman")) {
        Write-Host "Installing Podman Desktop..."
        brew install --cask podman-desktop
    } else {
        Write-Host "✔ Podman Desktop already installed." -ForegroundColor Green
    }

    # VS Code Remote Tools
    Write-Host "`nInstalling VS Code Remote Tools..." -ForegroundColor Yellow
    $extensions = @(
        "ms-vscode-remote.vscode-remote-extensionpack",
        "ms-vscode-remote.remote-containers",
        "ms-vscode-remote.remote-ssh",
        "vscjava.vscode-java-pack"
    )

    $installed = code --list-extensions

    foreach ($ext in $extensions) {
        if ($installed -contains $ext) {
            Write-Host "✔ $ext already installed." -ForegroundColor Green
        } else {
            Write-Host "Installing $ext..."
            code --install-extension $ext
        }
    }

    Write-Host "`nmacOS setup complete!" -ForegroundColor Cyan
    exit 0
}

# -------------------------------
# Windows Setup
# -------------------------------
if ($IsWindows) {
    Write-Host "`n=== Windows Setup ===" -ForegroundColor Cyan

    $TempDir = "$env:TEMP\devtools"
    New-Item -ItemType Directory -Force -Path $TempDir | Out-Null

    # Git
    if (-not (Test-Command "git")) {
        Write-Host "Installing Git..."
        $gitInstaller = "$TempDir\git.exe"
        Download-File "https://github.com/git-for-windows/git/releases/latest/download/Git-64-bit.exe" $gitInstaller
        Start-Process $gitInstaller -ArgumentList "/VERYSILENT" -Wait
    } else {
        Write-Host "✔ Git already installed." -ForegroundColor Green
    }

    # GitHub Desktop
    if (-not (Test-Command "github")) {
        Write-Host "Installing GitHub Desktop..."
        $ghdInstaller = "$TempDir\github-desktop.exe"
        Download-File "https://central.github.com/deployments/desktop/desktop/latest/win32" $ghdInstaller
        Start-Process $ghdInstaller -ArgumentList "/SILENT" -Wait
    } else {
        Write-Host "✔ GitHub Desktop already installed." -ForegroundColor Green
    }

    # VS Code
    if (-not (Test-Command "code")) {
        Write-Host "Installing Visual Studio Code..."
        $vscodeInstaller = "$TempDir\vscode.exe"
        Download-File "https://update.code.visualstudio.com/latest/win32-x64-user/stable" $vscodeInstaller
        Start-Process $vscodeInstaller -ArgumentList "/VERYSILENT" -Wait
    } else {
        Write-Host "✔ VS Code already installed." -ForegroundColor Green
    }

    # Podman Desktop
    if (-not (Test-Command "podman")) {
        Write-Host "Installing Podman Desktop..."
        $podmanInstaller = "$TempDir\podman-desktop.msi"
        Download-File "https://github.com/containers/podman-desktop/releases/latest/download/podman-desktop-setup-x64.msi" $podmanInstaller
        Start-Process "msiexec.exe" -ArgumentList "/i `"$podmanInstaller`" /qn" -Wait
    } else {
        Write-Host "✔ Podman Desktop already installed." -ForegroundColor Green
    }

    # Notepad++ (Windows only)
    if (-not (Test-Command "notepad++")) {
        Write-Host "Installing Notepad++..."
        $npInstaller = "$TempDir\npp.exe"
        Download-File "https://github.com/notepad-plus-plus/notepad-plus-plus/releases/latest/download/npp.8.6.2.Installer.x64.exe" $npInstaller
        Start-Process $npInstaller -ArgumentList "/S" -Wait
    } else {
        Write-Host "✔ Notepad++ already installed." -ForegroundColor Green
    }

    # VS Code Remote Tools
    Write-Host "`nInstalling VS Code Remote Tools..." -ForegroundColor Yellow
    $extensions = @(
        "ms-vscode-remote.vscode-remote-extensionpack",
        "ms-vscode-remote.remote-containers",
        "ms-vscode-remote.remote-ssh",
        "vscjava.vscode-java-pack"
    )

    $installed = code --list-extensions

    foreach ($ext in $extensions) {
        if ($installed -contains $ext) {
            Write-Host "✔ $ext already installed." -ForegroundColor Green
        } else {
            Write-Host "Installing $ext..."
            code --install-extension $ext
        }
    }

    Write-Host "`nWindows setup complete!" -ForegroundColor Cyan
}

