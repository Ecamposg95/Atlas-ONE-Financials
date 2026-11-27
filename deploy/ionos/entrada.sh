#!/bin/bash
# Único comando que la llave de deploy de GitHub Actions puede ejecutar en atlas-prod-01 (comando forzado en el
# authorized_keys del usuario `deploy`). Recibe un SHA, comprueba que esté en main y llama al deploy.sh INSTALADO en
# el servidor, no al del commit: un commit malicioso en main no puede cambiar cómo se despliega ni con qué permisos.
#
# Se instala a mano, con dueño root (ver README.md). Al ser la puerta de entrada, no se actualiza sola.
set -euo pipefail

APP=/srv/apps/financials
SRC=$APP/src
SHA="${SSH_ORIGINAL_COMMAND:-${1:-}}"

if ! [[ "$SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "entrada: se esperaba un SHA de 40 caracteres y nada más" >&2
  exit 2
fi

cd "$APP"
exec 9>"$APP/estado/.deploy.lock"
if ! flock -n 9; then
  echo "entrada: ya hay un deploy en curso" >&2
  exit 3
fi

# Sin hooks: el clon es del usuario `deploy` y git los ejecutaría en el checkout.
GIT=(git -C "$SRC" -c core.hooksPath=/dev/null)
"${GIT[@]}" fetch --quiet origin main
if ! "${GIT[@]}" merge-base --is-ancestor "$SHA" origin/main; then
  echo "entrada: $SHA no está en main; no se despliega" >&2
  exit 4
fi
"${GIT[@]}" checkout --quiet --force --detach "$SHA"
# Nada que no esté en el commit entra al build (el Dockerfile hace COPY . .).
"${GIT[@]}" clean -fdxq

exec "$APP/deploy.sh" "$SHA"
