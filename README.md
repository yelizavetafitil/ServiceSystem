# Система гарантийного и постгарантийного обслуживания ЭМСТПН

Веб-платформа для РУП «Белнипиэнергопром»: личный кабинет заказчиков (энергосбытовые организации), тикет-система с SLA, репозиторий плагинов, база знаний и видеоинструкции.

## Быстрый старт (Docker)

```bash
docker compose up -d --build
docker compose --profile seed run --rm seed
```

Открыть: **http://localhost:8095**

Пересоздать БД с расширенными тестовыми данными:

```bash
docker compose --profile seed run --rm seed python seed.py --force
# или полный сброс тома PostgreSQL:
docker compose down -v && docker compose up -d --build
docker compose --profile seed run --rm seed python seed.py --force
```

## Тестовые учётные записи

| Роль | Email | Пароль |
|------|-------|--------|
| Администратор | admin@belnipi.by | admin123 |
| Аудитор (ГИП) | auditor@belnipi.by | auditor123 |
| Исполнитель | executor@belnipi.by | executor123 |
| Исполнитель 2 | executor2@belnipi.by | executor123 |
| Заказчик (Брест) | kozlov@brestenergo.by | customer123 |
| Заказчик (Брест 2) | ivanova@brestenergo.by | customer123 |
| Заказчик (Витебск) | sidorov@vitebskenergo.by | customer123 |
| Заказчик (Минск, suspended) | petrov@minskenergo.by | customer123 |

**Мастер-ключи организаций** (для первичной регистрации):
- `master_brest` / `MasterBrest2026!`
- `master_vitebsk` / `MasterVitebsk2026!`
- `master_minsk` / `MasterMinsk2026!`
- `master_gomel` / `MasterGomel2026!` (договор расторгнут — вход заблокирован)

## Чеклист проверки функциональности

### 3.1 Авторизация
1. `/register` → мастер-ключ `master_brest` → форма с согласием на ПДн → новый пользователь наследует договор
2. Вход `petrov@minskenergo.by` — режим «только чтение» (suspended)
3. Попытка входа пользователя с расторгнутым договором (после регистрации через gomel) — блокировка

### 3.2 Личный кабинет (kozlov@brestenergo.by)
1. **Плагины** — 4 из 5 (без «Отчёты НТД»), скачивание + changelog, архивная v2.3.0 у heat-calc
2. **Видео** — 2 из 3, главы с описаниями
3. **Туториалы** — все 6, Markdown-рендер, поиск
4. **Тикеты** — список своих заявок, создание новой с вложениями (chunk upload)
5. Баннер «договор истекает через ~25 дней» в шапке

### 3.3 Админка (admin@belnipi.by)
1. Договоры — 4 статуса (warranty / post-warranty / suspended / terminated)
2. Видимость контента по договору
3. Маршрутизация категорий → аудитор / исполнитель
4. CMS: плагины, туториалы, видео, категории
5. Журнал аудита и аудит пользователя

### 3.4–3.7 Тикеты
| № | Статус | Кто проверяет |
|---|--------|---------------|
| Т-2026-00001 | new | auditor — назначить исполнителя |
| Т-2026-00002 | in_progress | executor — ответ на проверку |
| Т-2026-00003 | on_review | auditor — готов к выдаче / отклонить |
| Т-2026-00004 | ready | auditor — утвердить решение |
| Т-2026-00005 | resolved | customer — видит официальный ответ и T1/T2 |
| Т-2026-00006 | rejected | customer — видит отклонение |
| Т-2026-00007 | in_progress, priority_changed | auditor — переквалификация P4→P2 |

### 4 REST API
- Swagger: http://localhost:8095/api/v1/docs/ui
- `GET /api/v1/knowledge?q=гидравлика`
- `GET /api/v1/videos/interface-overview` — chapters с description

### 5 Нефункциональные
- Idle logout 60 мин (клиент + сервер)
- `docker compose --profile backup up -d` — резервное копирование

## Реализованные требования ТЗ

- Двухэтапная авторизация (мастер-ключ → персональная регистрация с согласием на ПДн)
- Личный кабинет: плагины, видео, база знаний, тикеты
- Админ-панель: договоры, SLA, видимость контента, CMS
- Тикет-система с каскадными категориями, 4 уровнями критичности, SLA-таймерами
- Переквалификация приоритета только аудитором с обязательным обоснованием
- АРМ аудитора/исполнителя с вкладками и историей изменений
- Chunked upload файлов до 1 ГБ с resume
- REST API `/api/v1/tickets`, `/api/v1/knowledge`, `/api/v1/videos` для будущей LLM-интеграции
- Неизменяемый журнал аудита (PostgreSQL triggers)
- Сессия 60 мин без активности

## REST API (TZ раздел 4 — LLM/RAG)

Документация OpenAPI: **GET /api/v1/docs** · Swagger UI: **GET /api/v1/docs/ui**

Аутентификация:
- сессия пользователя (cookie после входа), или
- заголовок `X-API-Key: <LLM_API_KEY>` (env) для сервисной индексации базы знаний

```
GET /api/v1/tickets              # список заявок (ACL)
GET /api/v1/tickets/<id>         # заявка + история
GET /api/v1/knowledge?q=поиск    # туториалы, content_format=markdown
GET /api/v1/knowledge/<slug>     # одна статья
GET /api/v1/videos               # видео + chapters[].description (п. 4.3)
GET /api/v1/videos/<slug>        # одно видео с тайм-кодами
```

Туториалы хранятся в PostgreSQL как Markdown (`content_md`) для RAG (п. 4.2).
Видеоглавы содержат `title`, `start_sec`, `description` для перенаправления ИИ (п. 4.3).

## Нефункциональные требования (раздел 5)

| Пункт | Реализация |
|-------|------------|
| 5.1.1 Закон № 99-З | Согласие на регистрации, `/privacy`, `pd_consent_at` |
| 5.1.2 HTTPS | `FORCE_HTTPS=1`, HSTS, secure cookie |
| 5.1.3 Роли / 60 мин | RBAC, `PERMANENT_SESSION_LIFETIME`, server + client idle logout |
| 5.1.4 Неизменяемые логи | PostgreSQL triggers на `audit_logs`, `ticket_history` |
| 5.2.2 Chunked upload | 8 МБ чанки, resume 5 мин (`UPLOAD_SESSION_TTL_MINUTES`) |
| 5.2.3 Maintenance | `MAINTENANCE_MESSAGE` + `MAINTENANCE_AT` в шапке ЛК |
| 5.3.2 Object storage | `STORAGE_BACKEND=local\|s3` |
| 5.5.2 Backup | `docker compose --profile backup up -d` (ежемесячно, 3 архива) |

**Backup:** `docker compose --profile backup up -d`

**Production HTTPS:** reverse-proxy (nginx) + `FORCE_HTTPS=1`

## Структура

```
ServiceSystem/
├── app.py / wsgi.py
├── servicesystem/     # Flask-приложение
├── templates/         # Jinja2 шаблоны
├── static/            # CSS, JS
├── seed.py            # Тестовые данные
├── docker-compose.yml
└── Dockerfile
```

## Локальный запуск без Docker

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# PostgreSQL должен быть доступен
python seed.py
python app.py
```
