param(
    [string]$Distro = "",
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

    if ($normalized -match '^[\\]{2}wsl(?:\.localhost)?\([^\]+)\(.*)$') {
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

    $linuxPath = (& wsl.exe -d $RequestedDistro wslpath -a $InputPath).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($linuxPath)) {
        throw "Unable to convert path to WSL path for distro '$RequestedDistro': $InputPath"
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
& code --remote "wsl+$($resolved.Distro)" $resolved.LinuxPath
