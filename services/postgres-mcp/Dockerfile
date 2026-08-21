FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system postgres-mcp \
    && useradd --system --gid postgres-mcp --home-dir /app postgres-mcp
WORKDIR /app

COPY services/postgres-mcp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

COPY drivers/dm/ /opt/dm-driver/
RUN set -eu; \
    wheel=$(find /opt/dm-driver -maxdepth 1 -type f -name '*.whl' -print -quit); \
    if [ -n "$wheel" ]; then pip install --no-cache-dir "$wheel"; fi

COPY services/postgres-mcp/hermes_postgres_mcp ./hermes_postgres_mcp
RUN chown -R postgres-mcp:postgres-mcp /app

USER postgres-mcp
EXPOSE 8091
CMD ["python", "-m", "hermes_postgres_mcp.server"]
