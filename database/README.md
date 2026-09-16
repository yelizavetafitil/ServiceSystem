# Дамп БД для развёртывания

Файл `servicesystem_seed.sql` — снимок PostgreSQL 16 со **схемой** и **демо-данными** (организации, договоры, пользователи, тикеты, контент).

## Восстановление в Docker

```bash
docker compose up -d db
docker compose exec -T db psql -U servicesystem -d postgres -c "DROP DATABASE IF EXISTS servicesystem;"
docker compose exec -T db psql -U servicesystem -d postgres -c "CREATE DATABASE servicesystem;"
docker compose exec -T db psql -U servicesystem -d servicesystem < database/servicesystem_seed.sql
docker compose up -d web
```

Альтернатива — пересоздание через Python: `docker compose --profile seed run --rm seed python seed.py --force`

## Обновить дамп в репозитории

После изменения seed или данных на стенде:

```bash
docker compose exec -T db pg_dump -U servicesystem --no-owner --no-acl servicesystem > database/servicesystem_seed.sql
git add database/servicesystem_seed.sql
git commit -m "Update database seed dump"
```
