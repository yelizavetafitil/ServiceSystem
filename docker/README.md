# Docker: офлайн-сборка web

Образ **не обращается к PyPI** при `docker build` — зависимости берутся из **`pydeps.tgz`** (архив `site-packages` для Python 3.12).

## Обычный запуск

```powershell
$env:DOCKER_BUILDKIT = "1"
docker compose build web
docker compose up -d db web
```

Приложение: http://localhost:8095

Код `servicesystem/`, `templates/`, `static/` монтируется с хоста — после правок достаточно `docker compose restart web`.

## Обновить зависимости (requirements.txt)

1. Поднять web: `docker compose up -d web`
2. При рабочем интернете: `.\scripts\refresh-docker-pydeps.ps1`
3. `docker compose build web && docker compose up -d web`

## Почему так

В Docker Desktop часто нет доступа к PyPI (`Network is unreachable`), из-за чего падает `pip install` при сборке. Архив в репозитории делает сборку стабильной на любой машине.
