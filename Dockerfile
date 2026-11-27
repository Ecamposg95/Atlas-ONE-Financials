# syntax=docker/dockerfile:1.6
#
# Imagen de producción de Atlas ONE Financials (VPS de IONOS, detrás de Caddy).
# Hace lo mismo que hacía Railway (Railpack):
#   1. npm ci && npm run build  -> frontend/dist
#   2. pip install -r requirements.txt
#   3. alembic upgrade head && uvicorn app.main:app (sirve la SPA desde frontend/dist)

# --- Etapa 1: la SPA de React ------------------------------------------------
FROM node:20-alpine AS frontend

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --include=dev
COPY frontend/ ./
RUN npm run build


# --- Etapa 2: dependencias de Python en un venv ------------------------------
FROM python:3.11-slim AS pydeps

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt


# --- Etapa 3: ejecución -------------------------------------------------------
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Mexico_City

COPY --from=pydeps /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . .
COPY --from=frontend --chown=app:app /frontend/dist ./frontend/dist

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

# Las migraciones corren al arrancar, igual que en Railway: un solo head, nunca create_all().
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
