# Система гарантийного и постгарантийного обслуживания ЭМСТПН

Веб-платформа для РУП «Белнипиэнергопром»: личный кабинет заказчиков (энергосбытовые организации), тикет-система с SLA, репозиторий плагинов, база знаний и видеоинструкции.

## Быстрый старт (Docker)

```bash
docker compose up -d --build
docker compose --profile seed run --rm seed
```

Открыть: **http://localhost:8095**

## Тестовые учётные записи

| Роль | Email | Пароль |
|------|-------|--------|
| Администратор | admin@belnipi.by | admin123 |
| Аудитор (ГИП) | auditor@belnipi.by | auditor123 |
| Исполнитель | executor@belnipi.by | executor123 |
| Заказчик (Брест) | kozlov@brestenergo.by | customer123 |

**Мастер-ключи организаций** (для первичной регистрации):
- `master_brest` / `MasterBrest2026!`
- `master_vitebsk` / `MasterVitebsk2026!`
- `master_minsk` / `MasterMinsk2026!`

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

## REST API

```
GET /api/v1/tickets
GET /api/v1/tickets/<id>
GET /api/v1/knowledge?q=поиск
GET /api/v1/videos
```

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
