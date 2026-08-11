FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app

COPY services/mcp-gateway/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

COPY services/mcp-gateway/hermes_mcp_gateway ./hermes_mcp_gateway
RUN chown -R app:app /app

USER app
EXPOSE 8090

CMD ["python", "-m", "hermes_mcp_gateway.server"]
