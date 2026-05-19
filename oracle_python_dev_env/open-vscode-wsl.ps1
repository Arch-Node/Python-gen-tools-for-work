param(
    [string]$Distro = "podman-machine-default",
    [string]$Path = ""
)

$ErrorActionPreference = "Stop"

function Resolve-WslLocation {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InputPath,

        [string]$RequestedDistro = ""
    )

    $normalized = $InputPath -replace "/", "\"

    if ($normalized -match '^[\\]{2}wsl(?:\.localhost)?\(([^)]+)\)(.*)$') {
        $detectedDistro = $Matches[1]
        $relativePath = $Matches[2] -replace "\\", "/"

        return @{
            Distro = $detectedDistro
            LinuxPath = "/$relativePath"
        }
    }

    if ([string]::IsNullOrWhiteSpace($RequestedDistro)) {
        throw "Distro is required when launching from a Windows path. Pass -Distro <name>."
    }

    $linuxPath = ""
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $linuxPath = (& wsl.exe -d $RequestedDistro wslpath -a "$InputPath" 2>$null).Trim()
    } catch {
        $linuxPath = ""
    }
    $ErrorActionPreference = $prevEAP
    
    if ([string]::IsNullOrWhiteSpace($linuxPath)) {
        # Fallback: manually convert Windows path to WSL path format
        $drive = ([System.IO.Path]::GetPathRoot($InputPath).TrimEnd('\') -replace ':','').toLower()
        $rest = $InputPath.Substring(2) -replace "\\", "/"
        $linuxPath = "/mnt/$drive$rest"
    }

    return @{
        Distro = $RequestedDistro
        LinuxPath = $linuxPath
    }
}

if (-not (Get-Command code -ErrorAction SilentlyContinue)) {
    throw "VS Code CLI 'code' was not found in PATH. Install VS Code and enable the shell command."
}

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "wsl.exe was not found. This launcher requires Windows Subsystem for Linux."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$targetPath = if ([string]::IsNullOrWhiteSpace($Path)) { $scriptDir } else { $Path }
$resolved = Resolve-WslLocation -InputPath $targetPath -RequestedDistro $Distro

Write-Host "Opening VS Code in WSL distro '$($resolved.Distro)' at '$($resolved.LinuxPath)'"

# Set up docker-to-podman shim in WSL distro
Write-Host "Setting up podman/docker in WSL distro..."
wsl.exe -d "$($resolved.Distro)" bash -c @'
# Create docker wrapper script
mkdir -p /usr/local/bin
cat > /tmp/docker-shim.sh << 'ENDSCRIPT'
#!/usr/bin/env bash
exec podman "$@"
ENDSCRIPT
chmod +x /tmp/docker-shim.sh
# Try to install system-wide, fall back to user bin
sudo mv /tmp/docker-shim.sh /usr/local/bin/docker 2>/dev/null || mv /tmp/docker-shim.sh ~/.local/bin/docker 2>/dev/null || true
'@ | Out-Null

# Add this directory to PATH for docker shim (Windows side)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PATH = "$scriptDir;$env:PATH"

# Set podman environment variables
$env:DOCKER_HOST = "unix:///run/user/1000/podman/podman.sock"
$env:CONTAINER_HOST = $env:DOCKER_HOST
$env:CONTAINER_RUNTIME = "podman"

# Launch VS Code connected to WSL distro
# Dev Containers extension will automatically detect devcontainer.json and prompt to reopen
Write-Host "Launching VS Code (Dev Containers will prompt to open in container)..."
& code --remote "wsl+$($resolved.Distro)" "$($resolved.LinuxPath)"
