# Deploy de Atlas ONE Financials en IONOS (`atlas-prod-01`)

`https://financials.atlasone.com.mx` · contenedor `financials` en la red `edge`, detrás de Caddy · base
`atlas_financials` en el PostgreSQL compartido del servidor.

## Por qué así

El servidor es compartido: ahí viven el Postgres con todas las bases, Caddy y las demás apps de Atlas. El deploy
anterior entraba **como root** con una llave guardada en GitHub: quien pudiera leer ese secreto, o empujar un
workflow a cualquier rama, quedaba como root de todo. Con este esquema:

- La llave que guarda GitHub entra como `deploy` (sin root) y en el servidor **sólo puede ejecutar `entrada.sh`**.
- `entrada.sh` acepta un SHA de 40 caracteres que esté en `main`, y nada más.
- `entrada.sh`, `deploy.sh` y `docker-compose.yml` están **instalados en el servidor con dueño root**. Del commit
  sólo salen el `Dockerfile` y el código: un commit malicioso en `main` no puede cambiar cómo se despliega, montar
  el disco del servidor ni pedir privilegios.
- El contenedor corre sin root, sin capacidades, con disco de sólo lectura y con tope de CPU, memoria y procesos.
- Cada imagen lleva la etiqueta de su commit. Si la versión nueva no llega a estar sana, vuelve sola la anterior.

Lo que este esquema **no** evita: quien logre empujar a `main` despliega código dentro del contenedor, con acceso
a la base y los secretos de Financials. `main` debe tener reglas de rama (el repo es público: son gratis).

| Archivo | Qué hace | Dónde se instala |
|---|---|---|
| `entrada.sh` | Único comando de la llave de GitHub: valida el SHA y llama a `deploy.sh` | `/srv/apps/financials/entrada.sh` (root, 755) |
| `deploy.sh` | build → migración → cambio de contenedor → salud → vuelta atrás si falla | `/srv/apps/financials/deploy.sh` (root, 755) |
| `docker-compose.yml` | Cómo corre el contenedor: límites, sólo lectura, healthcheck | `/srv/apps/financials/docker-compose.yml` (root, 644) |

## Instalación (una vez, como root)

Los nombres de contenedores y la subred de `edge` hay que confirmarlos antes (`docker ps`,
`docker network inspect edge`). Con la subred confirmada, acotar los proxies de confianza a ella con
`FINANCIALS_FORWARDED_ALLOW_IPS` (por omisión se confía en los rangos privados de Docker).

1. Usuario `deploy` (si no existe ya por Cortex): sin contraseña, en el grupo `docker`.

   ```
   id deploy || useradd --create-home --shell /bin/bash --groups docker deploy
   ```

   El grupo `docker` equivale a root en el servidor. Por eso el control real es el comando forzado del paso 4, y por
   eso los tres archivos de arriba son de root y no del usuario `deploy`.

2. Carpetas. `src` y `estado` son de `deploy`; todo lo demás, de root.

   ```
   install -d -o root -g root -m 755 /srv/apps/financials
   install -d -o deploy -g deploy -m 700 /srv/apps/financials/estado
   chown root:deploy /srv/apps/financials/.env && chmod 640 /srv/apps/financials/.env
   rm -rf /srv/apps/financials/src                       # lo que subía la tarea vieja (sin .git)
   sudo -u deploy git clone https://github.com/Ecamposg95/Atlas-ONE-Financials.git /srv/apps/financials/src
   ```

3. Los tres archivos, desde el clon, **revisados antes de copiarlos**:

   ```
   cd /srv/apps/financials/src/deploy/ionos
   install -o root -g root -m 755 entrada.sh deploy.sh /srv/apps/financials/
   install -o root -g root -m 644 docker-compose.yml /srv/apps/financials/
   ```

   No se actualizan solos. Cuando cambien en el repo, se revisa el diff y se repite este paso.

4. Llave nueva para GitHub Actions (no reutilizar la de root):

   ```
   ssh-keygen -t ed25519 -N '' -C 'github-actions financials' -f /root/financials_deploy
   install -d -m 755 /etc/ssh/authorized_keys
   printf 'restrict,command="/srv/apps/financials/entrada.sh" %s\n' "$(cat /root/financials_deploy.pub)" \
     >> /etc/ssh/authorized_keys/deploy
   chown root:root /etc/ssh/authorized_keys/deploy && chmod 644 /etc/ssh/authorized_keys/deploy
   ```

   En `/etc/ssh/sshd_config.d/10-deploy.conf` (y `sshd -t && systemctl reload ssh`):

   ```
   Match User deploy
       AuthorizedKeysFile /etc/ssh/authorized_keys/%u
       PasswordAuthentication no
   ```

   Así el usuario `deploy` no puede editar su propio `authorized_keys` para quitarse el comando forzado. Si Cortex
   ya usa `/home/deploy/.ssh/authorized_keys`, mover esa línea al archivo nuevo en el mismo paso.

   La privada (`/root/financials_deploy`) va al secreto `IONOS_DEPLOY_KEY` del repo y se borra del servidor.

5. Primer deploy a mano, para dejar una imagen con etiqueta a la que volver:

   ```
   sudo -u deploy /srv/apps/financials/entrada.sh "$(git -C /srv/apps/financials/src rev-parse origin/main)"
   ```

6. Comprobar el candado, desde otra máquina y con la llave nueva:

   ```
   ssh -i financials_deploy deploy@74.208.190.44 id            # responde el error de entrada.sh, no `uid=`
   ssh -i financials_deploy deploy@74.208.190.44 0000000000000000000000000000000000000000   # "no está en main"
   ```

7. En GitHub: variable `DESPLIEGUE_SEGURO=true`. La tarea vieja deja de correr. Cuando un deploy completo haya
   pasado por la tarea nueva: borrar el secreto `IONOS_SSH_KEY`, **quitar esa llave del `authorized_keys` de root**
   y abrir un PR que elimine la tarea `deploy-root` de `ci.yml` y el bloque `build` del compose.

## Operación

- **Deploy a mano** (como `deploy`): `/srv/apps/financials/entrada.sh <sha de main>`.
- **Volver a una versión anterior** (su imagen sigue ahí; se guardan 3), sin tocar la base:
  `sudo -u deploy /srv/apps/financials/deploy.sh <sha anterior> --sin-migracion`. La base no retrocede: por eso las
  migraciones son aditivas.
- **Logs**: `docker logs financials --tail 200`; los del deploy, en `/srv/apps/financials/estado/`.
- **Comando suelto**: `docker exec financials python -m <módulo>`.

## Pendiente fuera de este repo

- **Respaldos.** `atlas_financials` entra en el dump nocturno del servidor (14 días, mismo disco). La contabilidad
  y los adjuntos deben conservarse 5 años (CFF art. 30): falta la copia externa con esa retención y una
  restauración probada. Plan en `atlas-cortex`, `docs/superpowers/` (pista de infraestructura, bloque S1).
- **Base**: `REVOKE ALL ON DATABASE atlas_financials FROM PUBLIC` y límite de conexiones del rol (bloque S3).
