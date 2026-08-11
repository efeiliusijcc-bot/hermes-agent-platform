FROM python:3.12.10-slim-bookworm@sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
WORKDIR /app

COPY services/knowledge-service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

COPY services/knowledge-service/hermes_knowledge_service ./hermes_knowledge_service
RUN chown -R app:app /app

USER app
EXPOSE 8081

CMD ["uvicorn", "hermes_knowledge_service.server:app", "--host", "0.0.0.0", "--port", "8081"]
