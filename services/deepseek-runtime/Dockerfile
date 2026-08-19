FROM node:22.19.0-bookworm-slim AS harness-runtime

RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/deepseek-harness
COPY services/deepseek-runtime/package.json services/deepseek-runtime/package-lock.json ./
RUN npm ci --omit=dev \
    && npm cache clean --force
COPY services/deepseek-runtime/platform-capabilities.mjs ./platform-capabilities.mjs

FROM python:3.12.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends bash git ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10004 deepseek \
    && useradd --system --uid 10004 --gid deepseek --home-dir /app deepseek

WORKDIR /app
COPY --from=harness-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=harness-runtime /opt/deepseek-harness /opt/deepseek-harness
COPY services/deepseek-runtime/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt

COPY services/deepseek-runtime/deepseek_runtime_service ./deepseek_runtime_service
COPY services/deepseek-runtime/cordis.yml ./cordis.yml
RUN mkdir -p /data/workspaces /data/deepseek-sessions \
    && chmod 0444 /app/cordis.yml \
    && chown -R deepseek:deepseek /app /data/deepseek-sessions

USER deepseek
EXPOSE 8770 8771
CMD ["uvicorn", "deepseek_runtime_service.server:app", "--host", "0.0.0.0", "--port", "8771"]
