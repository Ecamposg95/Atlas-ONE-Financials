#!/bin/bash
# Deploy de Atlas ONE Financials en atlas-prod-01. Lo llama entrada.sh con el clon ya en el commit a desplegar.
# Orden: build -> migración -> reemplazo del contenedor -> salud. Si algo falla queda la versión anterior.
# La migración NO se revierte: por eso las migraciones son aditivas.
#
# Se instala a mano con dueño root en /srv/apps/financials/deploy.sh, igual que docker-compose.yml (ver README.md).
# Del commit sólo salen el Dockerfile y el código.
#
#   deploy.sh <sha>                  deploy normal
#   deploy.sh <sha> --sin-migracion  volver a una imagen anterior ya construida, sin tocar la base
set -euo pipefail
umask 077

SHA="$1"
MODO="${2:-}"
APP="${FINANCIALS_APP_DIR:-/srv/apps/financials}"
SRC="$APP/src"
ENVF="$APP/.env"
EST="$APP/estado"                              # del usuario deploy: candado, logs y la etiqueta en uso
ESPERA_SALUD="${FINANCIALS_ESPERA_SALUD:-150}"  # segundos
CONSERVAR=3                                     # imágenes financials:<sha> que se guardan
LOG="$EST/deploy-$(date -u +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

compose() { FINANCIALS_APP_DIR="$APP" docker compose -p financials -f "$APP/docker-compose.yml" "$@"; }
sano() { [ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' financials 2>/dev/null)" = healthy ]; }
esperar_salud() {
  local fin=$((SECONDS + ESPERA_SALUD))
  while [ $SECONDS -lt $fin ]; do
    sano && return 0
    sleep 3
  done
  return 1
}
levantar() { FINANCIALS_TAG="$1" MIGRAR_AL_ARRANCAR=0 compose up -d --no-build; }

cd "$APP"
echo "== deploy financials $(date -u +%FT%TZ) -> $SHA ${MODO} =="
[ -f "$ENVF" ] || { echo "falta $ENVF"; exit 1; }
ANTERIOR="$(cat "$EST/.tag_actual" 2>/dev/null || true)"
echo "versión anterior: ${ANTERIOR:-ninguna}"

if [ "$MODO" = "--sin-migracion" ]; then
  docker image inspect "financials:$SHA" >/dev/null 2>&1 || { echo "no existe la imagen financials:$SHA"; exit 1; }
else
  echo "-- build"
  docker build --quiet -t "financials:$SHA" "$SRC"
  echo "-- migración (alembic upgrade head)"
  docker run --rm --network edge --env-file "$ENVF" "financials:$SHA" alembic upgrade head
fi

echo "-- reemplazo del contenedor"
levantar "$SHA"

echo "-- esperando salud (hasta ${ESPERA_SALUD}s)"
if esperar_salud; then
  echo "$SHA" > "$EST/.tag_actual"
  # Limpieza: quedan la imagen en uso, la anterior y las más recientes hasta $CONSERVAR. Nada de esto debe tumbar
  # un deploy que ya quedó sano (con pipefail, un grep sin resultados es un error): por eso el `|| true`.
  { docker images financials --format '{{.Tag}}' | grep -E '^[0-9a-f]{40}$' | grep -vx -e "$SHA" -e "${ANTERIOR:-x}" \
      | tail -n +$((CONSERVAR - 1)) | while read -r viejo; do docker rmi "financials:$viejo" >/dev/null 2>&1 || true; done; } || true
  { ls -1t "$EST"/deploy-*.log 2>/dev/null | tail -n +21 | xargs -r rm -f; } || true
  echo "== DEPLOY OK $(date -u +%FT%TZ) =="
  exit 0
fi

# El log de la app se queda en el servidor: esta salida viaja por SSH al log de GitHub Actions.
docker logs financials --tail 80 > "$EST/fallo-$(date -u +%Y%m%d-%H%M%S).log" 2>&1 || true
echo "-- la versión nueva no llegó a estar sana (su log quedó en $EST/fallo-*.log)"
if [ -n "$ANTERIOR" ] && [ "$ANTERIOR" != "$SHA" ] && docker image inspect "financials:$ANTERIOR" >/dev/null 2>&1; then
  echo "-- vuelta a $ANTERIOR"
  levantar "$ANTERIOR"
  esperar_salud && echo "versión anterior sana otra vez" || echo "ATENCIÓN: la versión anterior tampoco está sana"
else
  echo "ATENCIÓN: no hay versión anterior a la que volver"
fi
echo "== DEPLOY FALLIDO $(date -u +%FT%TZ) =="
exit 1
