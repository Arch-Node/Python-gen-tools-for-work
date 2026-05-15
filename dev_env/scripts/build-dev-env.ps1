param(
    [string[]]$Env,
    [switch]$Force
)

$Root = Resolve-Path "$(Join-Path $PSScriptRoot "..")"
$DevEnvRoot = Join-Path $Root "dev_env"

if (-not (Test-Path $DevEnvRoot)) {
    Write-Error "dev_env directory not found at $DevEnvRoot"
    exit 1
}

$environments = Get-ChildItem -Path $DevEnvRoot -Directory | Where-Object {
    $_.Name -ne 'scripts' -and $_.Name -ne 'oracle-client'
}

if ($Env.Count -gt 0) {
    $environments = $environments | Where-Object { $Env -contains $_.Name }
}

if ($environments.Count -eq 0) {
    Write-Error "No environments found to build."
    exit 1
}

foreach ($environment in $environments) {
    $name = $environment.Name
    $context = $environment.FullName
    $dockerfile = Join-Path $context 'Containerfile'

    if (-not (Test-Path $dockerfile)) {
        Write-Host "Skipping '$name': no Containerfile found." -ForegroundColor Yellow
        continue
    }

    if ($name -eq 'plsql-python') {
        $oracleClientDir = Join-Path $context 'oracle-client'
        if (-not (Test-Path $oracleClientDir)) {
            Write-Host "Skipping 'plsql-python': oracle-client files are required in $oracleClientDir." -ForegroundColor Yellow
            continue
        }
    }

    $imageName = "dev-env-$name:latest"
    Write-Host "Building image $imageName from $context" -ForegroundColor Cyan

    docker build -t $imageName $context
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to build $imageName"
        exit $LASTEXITCODE
    }

    Write-Host "Built $imageName successfully." -ForegroundColor Green
}
