# syntax=docker/dockerfile:1
# Python-зависимости ставятся из docker/pydeps.tgz (офлайн, без PyPI в Docker).
# Обновить архив после смены requirements.txt: scripts/refresh-docker-pydeps.ps1
FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UPLOAD_FOLDER=/app/data/uploads

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY docker/pydeps.tgz /tmp/pydeps.tgz
RUN tar xzf /tmp/pydeps.tgz -C /usr/local/lib/python3.12 \
    && rm /tmp/pydeps.tgz \
    && python -c "import flask, sqlalchemy, psycopg2; print('deps ok', flask.__version__)"

COPY . .

RUN mkdir -p /app/data/uploads/plugins /app/data/uploads/tickets /app/data/uploads/responses

EXPOSE 5000

CMD ["python", "-m", "gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "300", "--worker-class", "gthread", "wsgi:app"]
