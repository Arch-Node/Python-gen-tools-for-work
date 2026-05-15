<#
    Cross-Platform Java Dev Environment Builder
    -------------------------------------------
    Works on:
      - Windows PowerShell 5+
      - PowerShell Core (pwsh) on macOS

    Checks for:
      - Docker (Docker Desktop on Windows, Docker Engine on macOS)
      - Git
      - Visual Studio Code
      - VS Code Dev Containers extension

    Builds:
      - java-dev-env:latest Docker image
#>

Write-Host "=== Java Dev Environment Setup (Cross-Platform) ===" -ForegroundColor Cyan

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

# -------------------------------
# Check Docker
# -------------------------------
Write-Host "`nChecking Docker..." -ForegroundColor Yellow

if (-not (Test-Command "docker")) {
    Write-Host "❌ Docker is NOT installed." -ForegroundColor Red

    if ($IsWindows) {
        Write-Host "Install Docker Desktop: https://www.docker.com/products/docker-desktop"
    } elseif ($IsMacOS) {
        Write-Host "Install Docker Desktop for Mac: https://www.docker.com/products/docker-desktop"
    }

    exit 1
} else {
    Write-Host "✔ Docker found." -ForegroundColor Green
}

# -------------------------------
# Check Git
# -------------------------------
Write-Host "`nChecking Git..." -ForegroundColor Yellow

if (-not (Test-Command "git")) {
    Write-Host "❌ Git is NOT installed." -ForegroundColor Red

    if ($IsWindows) {
        Write-Host "Install Git for Windows: https://git-scm.com/download/win"
    } elseif ($IsMacOS) {
        Write-Host "Install Git via Homebrew: brew install git"
    }

    exit 1
} else {
    Write-Host "✔ Git found." -ForegroundColor Green
}

# -------------------------------
# Check VS Code
# -------------------------------
Write-Host "`nChecking Visual Studio Code..." -ForegroundColor Yellow

if (-not (Test-Command "code")) {
    Write-Host "❌ VS Code is NOT installed." -ForegroundColor Red

    Write-Host "Download VS Code: https://code.visualstudio.com/"
    exit 1
} else {
    Write-Host "✔ VS Code found." -ForegroundColor Green
}

# -------------------------------
# Check VS Code Dev Containers extension
# -------------------------------
Write-Host "`nChecking VS Code Dev Containers extension..." -ForegroundColor Yellow

$extensions = code --list-extensions

if ($extensions -notcontains "ms-vscode-remote.remote-containers") {
    Write-Host "❌ Dev Containers extension NOT installed." -ForegroundColor Red
    Write-Host "Installing extension..."
    code --install-extension ms-vscode-remote.remote-containers
} else {
    Write-Host "✔ Dev Containers extension installed." -ForegroundColor Green
}

# -------------------------------
# Build Docker Image
# -------------------------------
Write-Host "`nBuilding Docker image 'java-dev-env:latest'..." -ForegroundColor Cyan

docker build -t java-dev-env:latest .

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Docker build failed." -ForegroundColor Red
    exit 1
}

Write-Host "✔ Docker image built successfully!" -ForegroundColor Green

# -------------------------------
# Ask to run the container
# -------------------------------
Write-Host "`nWould you like to run the container now? (y/n)"
$run = Read-Host

if ($run -eq "y") {
    Write-Host "Starting container..." -ForegroundColor Cyan

    # macOS uses $PWD differently; this works on both platforms
    $workspace = (Get-Location).Path

    docker run -it --name java-dev `
        -v "$workspace:/workspace" `
        -w /workspace `
        java-dev-env:latest
} else {
    Write-Host "You can run it later with:" -ForegroundColor Yellow
    Write-Host "docker run -it --name java-dev -v `"`$(pwd)`":/workspace -w /workspace java-dev-env:latest"
}

Write-Host "`n=== Setup Complete ===" -ForegroundColor Cyan

