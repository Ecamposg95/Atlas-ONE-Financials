# syntax=docker/dockerfile:1.6
#
# Imagen de producción de Atlas ONE Financials (VPS de IONOS, detrás de Caddy).
# Hace lo mismo que hacía Railway (Railpack):
#   1. npm ci && npm run build  -> frontend/dist
#   2. pip install -r requirements.txt
#   3. alembic upgrade head (antes del cambio de contenedor) y uvicorn app.main:app (sirve la SPA desde frontend/dist)

# --- Etapa 1: la SPA de React ------------------------------------------------
FROM node:26-alpine AS frontend

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
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/deep', timeout=5)"

# Las migraciones corren ANTES de cambiar el contenedor (deploy/ionos/deploy.sh, con MIGRAR_AL_ARRANCAR=0): si una
# falla, la versión anterior sigue en pie en vez de quedar en un ciclo de reinicios. Sin esa variable se migra al
# arrancar, como antes (desarrollo y la tarea vieja de deploy). Un solo head, nunca create_all().
# Las IPs de proxy en las que uvicorn confía salen de FORWARDED_ALLOW_IPS (por omisión sólo 127.0.0.1).
CMD ["sh", "-c", "if [ \"${MIGRAR_AL_ARRANCAR:-1}\" = 1 ]; then alembic upgrade head; fi && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
