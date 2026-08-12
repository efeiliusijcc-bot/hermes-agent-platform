FROM python:3.12.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system --gid 10002 app && useradd --system --uid 10002 --gid app --home-dir /app app
WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

COPY backend/alembic.ini ./alembic.ini
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY docker/backend-entrypoint.sh /usr/local/bin/backend-entrypoint

RUN chmod 0555 /usr/local/bin/backend-entrypoint && chown -R app:app /app
USER app

EXPOSE 8000
ENTRYPOINT ["backend-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
