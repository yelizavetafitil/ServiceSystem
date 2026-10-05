# Сохранить установленные pip-пакеты из работающего web-контейнера в docker/pydeps.tgz
# (нужен интернет только при pip install внутри контейнера, не при docker build)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$container = "servicesystem-web-1"
$running = docker ps --filter "name=$container" --format "{{.Names}}"
if (-not $running) {
    Write-Host "Container $container is not running. Start: docker compose up -d web" -ForegroundColor Red
    exit 1
}

Write-Host "Updating packages in container from requirements.txt (needs network in container)..." -ForegroundColor Cyan
docker exec $container pip install -r /app/requirements.txt -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install failed (check VPN/internet). Existing pydeps.tgz unchanged." -ForegroundColor Yellow
    exit 1
}

Write-Host "Packing site-packages -> docker/pydeps.tgz ..." -ForegroundColor Cyan
docker exec $container bash -c "tar czf /tmp/pydeps.tgz -C /usr/local/lib/python3.12 site-packages"
docker cp "${container}:/tmp/pydeps.tgz" (Join-Path $root "docker\pydeps.tgz")
Write-Host "Done. Rebuild: docker compose build web" -ForegroundColor Green
