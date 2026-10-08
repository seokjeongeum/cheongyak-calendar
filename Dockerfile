# syntax=docker/dockerfile:1
FROM node:24-alpine AS web-build
WORKDIR /web
COPY web/package*.json ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm ci --no-audit --no-fund --strict-ssl=true
COPY web/index.html web/tsconfig.json web/vite.config.ts ./
COPY web/src ./src
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATIC_WEB_DIR=/app/static \
    PORT=8080

# Retain best-effort HWP extraction; hosted builds need no Docker socket.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY api/pyproject.toml ./
COPY api/app ./app
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir .
COPY --from=web-build /web/dist ./static
EXPOSE 8080
CMD ["python", "-m", "app.hosted_runner"]
