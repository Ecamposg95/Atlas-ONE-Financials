# 07 · Seguridad, fiscal y calidad

_Atlas ONE Financials (antes ARCA) · Corte: 2026-11-23 · Fase 0 — Discovery_

## Resumen ejecutivo

Los controles que protegen la integridad contable son sólidos y están probados: aislamiento por tenant, un único punto de asiento, candados de periodo, reversos y bitácora. Los controles de perímetro son más débiles: no hay límite de intentos en autenticación, los tokens viven en `localStorage` y no hay evidencia de respaldos probados.

En lo fiscal, el producto calcula IVA, retenciones y deducibilidad y genera contabilidad electrónica, pero **no maneja CFDI** y **ninguna regla fiscal ha sido validada en esta fase** contra documentación oficial ni por un contador. No debe afirmarse cumplimiento.

## Controles existentes (evidencia)

| Control | Implementación |
|---|---|
| Contraseñas | bcrypt (`app/security/passwords.py`); mínimo 8 caracteres (`app/domains/auth/schemas.py`) |
| Sesión | JWT HS256 con access y refresh; el claim `type` impide usar un refresh como access (`app/security/tokens.py`) |
| Secreto | En producción es obligatorio y de al menos 32 caracteres; sin valor por defecto (`app/config.py`) |
| Aislamiento por tenant | `organization_id` desde la membresía validada (`app/security/deps.py`); un recurso ajeno responde 404; `tests/test_tenant_isolation.py` |
| Roles | OWNER, ADMIN, ACCOUNTANT, MEMBER, VIEWER mediante `require_role`, usado en más de 70 endpoints |
| Autorización por monto | `app/services/approvals.py`: límite de captura, umbral y facultad de autorizar |
| Llaves de agente | Sólo se guarda sha256 y prefijo; fijas a una organización; con scopes (`app/security/agent.py`, `app/models/agent.py`) |
| Agentes y asistente | Sólo proponen; aprobar ejecuta el servicio real con permisos de un humano (ADR-005) |
| Inmutabilidad | Cancelación lógica y reversos; folios inmutables (`AGENTS.md` invariantes 8, 11, 17) |
| Bitácora | `change_log` append-only con valores anteriores, actor, motivo y origen |
| Adjuntos | Validación por extensión, tipo declarado y firma; límite de tamaño y cantidad; descarga con `nosniff` |
| Documentación de API | `/docs` y `/openapi.json` apagados en producción (`app/main.py`) |
| CORS | Lista explícita por variable de entorno |
| Presupuesto de IA | Tope en dólares por empresa y mes (`app/services/ai/budget.py`) |

## Modelo de amenazas

| # | Amenaza | Activo | Control actual | Brecha | Prioridad |
|---|---|---|---|---|---|
| T1 | Fuerza bruta o relleno de credenciales | Cuentas de usuario | bcrypt | Sin límite de intentos ni bloqueo | Alta |
| T2 | Robo de token por XSS | Sesión | — | Access y refresh en `localStorage`; access de 12 horas por defecto | Alta |
| T3 | Acceso entre organizaciones | Datos financieros | Filtro por membresía y pruebas | Cobertura de pruebas por muestreo, no por barrido | Media |
| T4 | Abuso de llave de agente filtrada | Lectura y propuestas | Hash, scopes, revocación | Sin límite de invocaciones; sin expiración de llave | Media |
| T5 | Inyección de instrucciones al asistente mediante datos (conceptos, adjuntos, importaciones) | Propuestas | El asistente sólo propone; aprobación humana | Sin evaluación sistemática | Media |
| T6 | Fraude interno: una persona captura y autoriza | Dinero | Umbral y facultad de autorizar | Sin regla que impida autorizar lo propio en todos los casos; sin matriz de segregación | Media |
| T7 | Escritura directa al libro saltando reglas | Integridad contable | Convención y revisión; un único punto de asiento | Sin restricción de cuadre en base de datos | Media |
| T8 | Pérdida de datos | Todo | Respaldos del proveedor (no verificados) | Sin prueba de restauración | Alta |
| T9 | Archivo malicioso en adjuntos o importación | Servidor, usuarios | Validación de firma y tipo | Sin análisis antimalware | Baja |
| T10 | Duplicado por reintento de integración | Integridad contable | Idempotencia por `source_id` en procesos periódicos | Sin restricción única; integraciones aún no existen | Media, al integrar |
| T11 | Exposición de secretos fiscales | Certificados y llaves | No se almacenan hoy | Diseño pendiente antes de timbrar | Bloqueante para PAC |
| T12 | Promesa de controles inexistentes | Confianza, responsabilidad | — | `docs/ARCHITECTURE.md` §9 describe cifrado de secretos fiscales y rate limiting que no existen | Alta, costo bajo |

## Matriz de permisos

### Vigente (evidencia parcial)

Los grupos de roles usados en los routers son `WRITE_ROLES`, `ACCOUNTING_ROLES`, `CATALOG_ROLES`, `SETTLEMENT_ROLES`, `SETTINGS_ROLES`, `CANCEL_ROLES` y `(OWNER, ADMIN)`. Su composición exacta por endpoint **no se enumeró en esta fase**; debe extraerse del código antes de publicar una matriz como definitiva.

Lo confirmado por documentación del repositorio:

| Acción | OWNER | ADMIN | ACCOUNTANT | MEMBER | VIEWER |
|---|---|---|---|---|---|
| Ver contabilidad | ✓ | ✓ | ✓ | — | — |
| Configurar umbrales de autorización | ✓ | ✓ | — | — | — |
| Poner o quitar la marca de la empresa | ✓ | — | — | — | — |
| Cargar histórico de análisis | ✓ | — | — | — | — |
| Fijar fecha de corte y estado de apertura | ✓ | ✓ | — | — | — |
| Autorizar por monto | Siempre | Si tiene la facultad | Si tiene la facultad | Si tiene la facultad | — |

### Brechas hacia enterprise (propuesta)

- Permisos por entidad legal, no sólo por organización.
- Permisos por acción más finos que el rol (por ejemplo, cerrar periodo separado de asentar pólizas).
- Entitlements por módulo evaluados en el backend, además del rol.

## Segregación de funciones (propuesta)

| Par de funciones | Regla propuesta | Estado |
|---|---|---|
| Capturar y autorizar la misma operación | Quien captura no autoriza, salvo el dueño en organizaciones de una sola persona | Parcial; verificar el caso del autorizador que captura |
| Entregar y recibir un corte de caja | Personas distintas, o un administrador | Implementado (`docs/MVP_STATUS.md`) |
| Asentar póliza manual y cerrar periodo | Configurable en enterprise | Ausente |
| Dar de alta proveedor y pagarle | Alerta en el primer pago a un proveedor nuevo | Ausente |
| Crear llave de agente y aprobar sus propuestas | Registrar; alertar si coincide | Ausente |
| Reabrir periodo | Exige motivo y queda registrado | Implementado |

## Casos de prueba contables

| Caso | Cubierto por | Agregar |
|---|---|---|
| Póliza descuadrada se rechaza | `tests/test_ledger.py` | — |
| Cualquier secuencia de operaciones deja la balanza cuadrada | — | Prueba de propiedad |
| Reverso emite póliza espejo y no se repite | `tests/test_reversos.py` | — |
| Mes cerrado no acepta pólizas | `tests/test_cierre_periodo.py` | — |
| Ejercicio cerrado y póliza de cierre | `tests/test_cierre_anual.py` | — |
| Folios consecutivos sin huecos ni repetidos bajo concurrencia | `tests/test_folios.py`, `tests/test_bloqueo_postgres.py` | — |
| Proceso periódico dos veces no duplica | `tests/test_activos_fijos.py`, `tests/test_recurrentes.py` | Mismo evento externo dos veces |
| Importación duplicada | `tests/test_importacion_*.py` | — |
| Auxiliares contra mayor | Parcial | CxC y CxP abiertas igual a sus cuentas de control |
| Reporte reproducible a fecha de corte | `tests/test_reports.py` | Mismo reporte antes y después de operaciones posteriores |
| Acceso entre organizaciones | `tests/test_tenant_isolation.py` | Barrido de todos los endpoints |
| Dos pagos simultáneos al mismo documento | — | Prueba de concurrencia en PostgreSQL |

## Respaldo y restauración

**Estado:** no verificable desde el repositorio. La base es PostgreSQL administrado en Railway; no hay scripts, runbooks ni registro de pruebas de restauración.

**Plan propuesto:**

1. Confirmar qué respaldos ofrece el plan contratado de Railway y su retención.
2. Definir objetivos: cuánto dato se acepta perder y en cuánto tiempo se debe recuperar. Son decisiones de negocio; no hay cifra propuesta sin esa conversación.
3. Agregar un volcado lógico periódico hacia almacenamiento fuera de Railway.
4. Probar la restauración en un entorno aparte y verificar: migraciones al día, balanza cuadrada por organización, conteo de pólizas y saldos igual al origen.
5. Documentar el procedimiento y repetir la prueba con una frecuencia acordada.

Nota: los adjuntos viven en la base (`attachment_blobs`), así que el respaldo de la base los incluye; al moverlos a almacenamiento de objetos habrá que respaldarlos aparte.

## Checklist de localización mexicana

Columna "Validado" se refiere a revisión contra documentación oficial o por un contador. **Nada está validado en esta fase.**

| Tema | Estado en código | Validado |
|---|---|---|
| IVA trasladado y acreditable | Implementado (`app/services/taxes.py`, `tests/test_iva.py`) | No |
| Retenciones de ISR e IVA | Implementado (`tests/test_retenciones.py`) | No |
| Aviso de deducibilidad | Implementado (`app/services/deductibility.py`) | No |
| Código agrupador del SAT en el catálogo | Implementado (`sat_codes.json`, `tests/test_sat_cuentas.py`) | No |
| Contabilidad electrónica: catálogo y balanza en XML | Implementado (`app/services/accounting/sat.py`, `tests/test_sat_xml.py`) | No |
| Pólizas en XML de contabilidad electrónica | No verificado | No |
| Exportación a CONTPAQi | Implementado (`contpaqi.py`, tres archivos de prueba) | No |
| CFDI 4.0: lectura de XML | Ausente | — |
| CFDI: validación de vigencia y cancelación | Ausente | — |
| Complemento de pago | Ausente | — |
| Notas de crédito | Ausente | — |
| Emisión y timbrado con PAC | Ausente | — |
| Almacenamiento de CSD o e.firma | Ausente; no debe iniciarse sin diseño de cifrado, rotación y permisos | — |
| Obligaciones por régimen fiscal | Ausente | — |
| Declaraciones | Fuera de alcance | — |

Distinciones que el diseño debe conservar: importar un documento no es validarlo; validarlo no es contabilizarlo; contabilizarlo no es declararlo. Un CFDI no equivale siempre a ingreso reconocido ni a efectivo cobrado.

## Inteligencia artificial

| Nivel de autonomía del task pack | Estado |
|---|---|
| 1. Lectura y explicación con permisos | Implementado (herramientas de lectura; el asistente corre como el usuario) |
| 2. Recomendación con justificación | Implementado mediante propuestas con evidencia |
| 3. Borrador validado por reglas deterministas | Implementado: aprobar ejecuta el servicio real con sus validaciones |
| 4. Ejecución autorizada con límites de riesgo | Ausente; no se propone abrirla todavía |

Reglas que se mantienen: el modelo nunca es fuente de verdad de saldos, cálculos fiscales ni asientos; no ejecuta transferencias, cancelaciones ni cierres; cada propuesta registra actor, evidencia, autorización y resultado.

## Acciones priorizadas

1. Límite de intentos y bloqueo en autenticación y en invocación por llave.
2. Corregir la documentación que promete controles inexistentes.
3. Verificar respaldos y hacer una prueba de restauración.
4. Reducir la vida del access token y evaluar mover el refresh a cookie `HttpOnly`.
5. Barrido automático de aislamiento por tenant.
6. Enumerar la matriz de permisos vigente desde el código.
7. Revisión fiscal por contador antes de cualquier copy de cumplimiento.

## Decisiones pendientes

1. Objetivos de pérdida y recuperación de datos.
2. Si la sesión migra a cookies `HttpOnly` (implica protección CSRF y cambios en el frontend).
3. Quién valida lo fiscal y con qué alcance.
4. Política de retención y borrado de datos de clientes.

## Riesgos

- Declarar cumplimiento, certificación o sustitución del contador sin evidencia.
- Iniciar timbrado sin arquitectura para certificados.
- Suponer que el respaldo del proveedor es suficiente sin haberlo restaurado nunca.
