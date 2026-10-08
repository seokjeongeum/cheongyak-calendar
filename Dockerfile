FROM node:24-alpine AS web-build
WORKDIR /web
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund --strict-ssl=true
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
RUN pip install --no-cache-dir .
COPY --from=web-build /web/dist ./static
EXPOSE 8080
CMD ["python", "-m", "app.hosted_runner"]
