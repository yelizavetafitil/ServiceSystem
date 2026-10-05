# Reliable local start: BuildKit + pip cache, then web + db.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))

$env:DOCKER_BUILDKIT = "1"
$env:COMPOSE_DOCKER_CLI_BUILD = "1"

Write-Host "Building web image (offline pydeps.tgz, no PyPI in build)..." -ForegroundColor Cyan
docker compose build web
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed. Ensure docker/pydeps.tgz exists (see docker/README.md)." -ForegroundColor Red
    exit 1
}

Write-Host "Starting db + web..." -ForegroundColor Cyan
docker compose up -d db web
docker compose ps
Write-Host "`nApp: http://localhost:8095" -ForegroundColor Green
