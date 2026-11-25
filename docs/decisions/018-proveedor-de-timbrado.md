# ADR-018 — Proveedor de timbrado detrás de una interfaz propia, con contingencia

**Fecha:** 2026-11-25 · **Estado:** aceptada (decisión D2 del founder, `docs/financials/09_MEGAPLAN_CFDI.md`)

> Numeración: ver ADR-017. Nada de esto está construido; la elección final del proveedor queda sujeta a cotejar la lista oficial del SAT y a cotizar.

## Contexto

- Financials sella el XML con el certificado del cliente (ADR-017). El proveedor autorizado de certificación (PAC) sólo valida, asigna UUID e incorpora el timbre del SAT.
- Según fuentes secundarias, el SAT revocó ocho proveedores en 2026, entre ellos SW sapien (13 de noviembre), Comercio Digital y Másfacturación (CONTPAQi). La lista oficial no se pudo abrir durante la investigación.
- Un proveedor revocado sólo puede certificar a clientes existentes durante 30 días, dentro de una transición de 90 (regla 2.7.2.12, fuente secundaria). Los comprobantes ya timbrados conservan validez; los timbres prepagados están en riesgo.
- Hay dos modelos en el mercado. Los revendedores (Facturapi, Facturama) reciben datos, sellan y timbran, y exigen el `.key` con su contraseña. Los PAC directos aceptan XML ya sellado; entre los vigentes según la investigación: Prodigia, Solución Factible, Formas Digitales, SIFEI, XPD y Diverza.
- La validación "no certificado previamente" es por proveedor: el mismo XML enviado a dos proveedores puede producir dos UUID.
- La cancelación se tramita ante el SAT por cualquier PAC autorizado, no necesariamente el que timbró. Requiere una solicitud firmada con el CSD del emisor. Qué proveedores aceptan una solicitud ya firmada, en vez de pedir el CSD, está **sin verificar** salvo SW.
- La biblioteca `satcfdi` (MIT) trae conector para Prodigia, entre otros.
- `docs/MEGA_PLAN_MVP.md` proponía Facturama, SW sapien o Finkok. El primero es revendedor, el segundo fue revocado y el tercero es hoy una marca que certifica otro proveedor. Este ADR lo sustituye.

Fuentes: `research_notes/Timbrado CFDI y conexión Atlas/comparacion_pac.md` y `cfdi40_sellado_cancelacion.md` (carpeta local, fuera de git).

## Decisión

### Interfaz propia

El módulo de localización (ADR-013) habla con cualquier proveedor a través de una sola interfaz, `ProveedorTimbrado`, con tres operaciones:

| Operación | Entra | Sale |
|---|---|---|
| `timbrar` | XML sellado, identificador idempotente del documento | Timbrado: UUID, XML timbrado tal como llegó, `RfcProvCertif`, `FechaTimbrado`. Rechazado: código del proveedor, código propio y mensaje en español. Indeterminado: sin respuesta |
| `cancelar` | Solicitud de cancelación ya firmada por el módulo de sellado (UUID, motivo, UUID sustituto si el motivo es 01) | Acuse del SAT o estado de la solicitud (en proceso, aceptada, rechazada por el receptor, no cancelable) |
| `consultar_estatus` | UUID, RFC del emisor, RFC del receptor, total | Estado ante el SAT (vigente, cancelado, no encontrado), si es cancelable y estado de la cancelación |

Cada proveedor es un adaptador que implementa las tres. Cambiar de proveedor es escribir un adaptador y mapear su catálogo de errores; no cambia el modelo de documento ni toca llaves.

Un proveedor que no acepte XML ya sellado, o que exija el CSD para cancelar, no es elegible: rompería ADR-017.

### Primario y contingencia

- **Primario a cotizar: Prodigia** (acepta XML sellado, ambiente de pruebas de autoservicio, conector en `satcfdi`).
- **Contingencia: Formas Digitales**, con Solución Factible como reserva. Formas Digitales publica precios, vende timbres sin caducidad, ofrece REST y SOAP y tiene credenciales de prueba públicas; falta una prueba de carga.
- **SIFEI queda descartado** mientras su cancelación documentada exija el PFX con su contraseña: rompe ADR-017.
- Cotejo de la lista oficial del SAT al 2026-11-25 (archivo JSON del portal, modificado el 20-11-2026): los cuatro candidatos siguen autorizados; las ocho revocaciones de 2026 se confirmaron en la relación oficial. Detalle en `research_notes/Timbrado CFDI y conexión Atlas/pac_fase0.md` (local, fuera de git).
- `satcfdi` sólo trae conector para Prodigia y únicamente para timbrar: la cancelación y el adaptador de contingencia se escriben aquí.
- **Manifiesto por proveedor.** La regla 2.7.2.7 de la RMF 2026 permite varios proveedores si el cliente entrega a cada uno su manifiesto, que Prodigia y Solución Factible piden firmado con la e.firma del cliente en su portal. Se piden los dos desde el alta de la empresa, para que la contingencia sirva sin demora.
- Condiciones para contratar cualquiera: aparece como autorizado en la lista oficial del SAT, cotejada a mano el día de la firma; acepta XML sellado; acepta cancelación con solicitud ya firmada; tiene mecanismo contra doble timbrado o consulta por identificador; ofrece timbres sin caducidad o pospago; entrega por escrito su política de confidencialidad y sus niveles de servicio.
- Los dos proveedores quedan con credenciales, saldo y adaptador vivos en producción. Se compran paquetes pequeños o pospago mientras siga la ola de revocaciones.
- El proveedor activo se configura por organización, con un valor por defecto global.

### Reglas de operación

- **Guardar antes de enviar.** El XML sellado se guarda antes de mandarlo; el XML timbrado se guarda byte a byte en cuanto llega. Reconstruirlo desde la base invalida los sellos.
- **Nunca enviar a la contingencia un documento con resultado indeterminado en el primario.** Si el primario no respondió, primero se consulta su estado (por identificador o UUID). Sólo se pasa a la contingencia lo que el primario rechazó o lo que nunca llegó a enviarse. Así se evita que un mismo documento tenga dos UUID.
- **Ventana de 72 horas.** Si un documento espera más de lo permitido entre su fecha y el timbrado, se vuelve a fechar y a sellar; el sello anterior se descarta.
- **Se registra `RfcProvCertif`** de cada timbre, para saber qué proveedor certificó cada documento.
- **Errores en español.** Cada adaptador traduce los códigos del proveedor a un catálogo propio. La pantalla distingue datos del receptor, certificado restringido o vencido, error técnico y saldo agotado.
- **Cancelación sin calcular el desenlace.** El estado final de una cancelación es el que devuelve `consultar_estatus`, no uno calculado por plazos (las guías del SAT dicen "tres días" y "72 horas hábiles" en distintos documentos).

### Plan ante revocación de un proveedor

1. Cotejo semanal de la lista oficial del SAT, más alerta por noticias.
2. Al conocerse la revocación del primario: cambiar el valor por defecto a la contingencia ese mismo día; no esperar el fin de los 30 días.
3. Cotizar y probar un nuevo secundario para recuperar la contingencia.
4. Los comprobantes ya timbrados siguen válidos; las cancelaciones pendientes se tramitan por el proveedor activo.

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Revendedor que sella y timbra (Facturapi, Facturama) | Exige el `.key` y la contraseña, contra ADR-017; no nombra qué PAC certifica detrás; ata el modelo de datos al suyo; su credencial de API emite por todas las empresas. A cambio daba menos trabajo inicial |
| Un solo PAC | Una revocación detiene la facturación de todos los clientes |
| Convertirse en PAC | Capital mínimo de diez millones de pesos, garantía, dictamen y supervisión del SAT; fuera de alcance |

## Consecuencias

- Financials arma y sella el XML (con `satcfdi` como candidato) y mantiene dos adaptadores con sus catálogos de errores.
- Dos contratos, dos saldos y una prueba periódica de la contingencia en ambiente de pruebas (fase 7).
- Prodigia, SIFEI y Solución Factible sólo cotizan a pedido; el costo real no se conoce hasta la fase 0. Referencia pública: Formas Digitales, de 0.56 a 1.98 pesos por timbre con IVA.
- El modelo de documento fiscal guarda el proveedor, el identificador idempotente, el XML sellado, el XML timbrado y el acuse de cancelación.

## Pendiente de verificar

- Lista oficial de proveedores autorizados (cotejo manual).
- Por proveedor: cancelación con solicitud ya firmada, mecanismo contra doble timbrado, versiones de complementos (pagos 2.0, nómina 1.2), costo de la cancelación.
- Qué pasa con los timbres prepagados de un proveedor revocado.
