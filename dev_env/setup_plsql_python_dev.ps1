# ==========================================================
# PL/SQL + Python Dev Pod (Oracle Thick Client)
# Podman | Cross-platform | PowerShell 7+
# ==========================================================

$ErrorActionPreference = "Stop"

Write-Host "== PL/SQL + Python Podman Dev Pod Setup =="

# ---- Names ----
$ImageName     = "plsql-python-dev:latest"
$ContainerName = "plsql-python-dev"
$PodName       = "plsql-python-dev-pod"

# ---- Paths ----
$RootDir       = Get-Location
$WorkspaceDir  = Join-Path $RootDir "workspace"
$OracleDir     = Join-Path $RootDir "oracle-client"
$EnvDir        = Join-Path $RootDir "env"
$SecretsDir    = Join-Path $RootDir "secrets"

# ---- Preconditions ----
function Require($cmd) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "Required command '$cmd' not found in PATH."
        exit 1
    }
}

Require "podman"
Require "pwsh"

if (-not (Test-Path $OracleDir)) {
    Write-Error "oracle-client directory not found. Place Instant Client zip files there."
    exit 1
}

# ---- Directory Layout ----
@($WorkspaceDir, $EnvDir, $SecretsDir) | ForEach-Object {
    if (-not (Test-Path $_)) {
        New-Item -ItemType Directory -Path $_ | Out-Null
        Write-Host "Created $($_)"
    }
}

# ---- Containerfile ----
$ContainerfilePath = Join-Path $RootDir "Containerfile"

if (-not (Test-Path $ContainerfilePath)) {
@'
FROM python:3.12-slim

# OS dependencies
RUN apt-get update && apt-get install -y \\
    unzip \\
    libaio1 \\
    curl \\
    openssh-client \\
 && rm -rf /var/lib/apt/lists/*

# Oracle Instant Client
ENV ORACLE_BASE=/opt/oracle
ENV LD_LIBRARY_PATH=\$ORACLE_BASE/instantclient
ENV PATH=\${PATH:}\$ORACLE_BASE/instantclient

WORKDIR /opt/oracle

COPY oracle-client/*.zip /opt/oracle/

RUN unzip instantclient-basiclite*zip && \\
    unzip instantclient-sqlplus*zip && \\
    ln -s instantclient_* instantclient && \\
    rm *.zip

# Python Oracle drivers
RUN pip install --no-cache-dir \\
    python-oracledb \\
    cx_Oracle

WORKDIR /workspace
CMD ["bash"]
'@ | Set-Content $ContainerfilePath -Encoding UTF8

Write-Host "Containerfile created"
}

# ---- Build Image ----
Write-Host "Building image..."
podman build -t $ImageName $RootDir

# ---- Pod Setup ----
if (podman pod exists $PodName 2>$null) {
    Write-Host "Removing existing pod..."
    podman pod rm -f $PodName | Out-Null
}

Write-Host "Creating pod..."
podman pod create --name $PodName

# ---- Run Container ----
Write-Host "Starting dev container in pod..."
podman run -it `
  --name $ContainerName `
  --pod $PodName `
  -v "${WorkspaceDir}:/workspace:Z" `
  -v "${SecretsDir}:/run/secrets:ro,Z" `
  --env-file "$EnvDir/.plsql.env" `
  $ImageName

Write-Host "✅ PL/SQL + Python dev pod ready"
