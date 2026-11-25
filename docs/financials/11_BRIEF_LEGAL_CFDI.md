# 11 · Brief legal: custodia del certificado de sello digital y datos personales

> **BORRADOR PARA REVISIÓN DE ABOGADO. NO ES ASESORÍA LEGAL.**
> Lo redactó el equipo de producto a partir de una investigación propia (noviembre de 2026). Las citas de ley vienen de los textos consolidados de la Cámara de Diputados (CFF con última reforma DOF 09-04-2026; LFPDPPP con última reforma DOF 14-11-2025), pero ninguna lectura ni conclusión de este documento ha sido revisada por un abogado. Las cláusulas son propuestas de trabajo, no texto contractual. Lo marcado **(sin verificar)** no se confirmó en fuente primaria.

_Atlas ONE Financials · 2026-11-25 · Decisión D6 del megaplan de CFDI (`09_MEGAPLAN_CFDI.md`)_

## 1. Qué se le pide al abogado

1. Revisar y redactar el contrato (o los términos de servicio y su anexo) por el que el cliente autoriza a Atlas ONE Financials a custodiar su certificado de sello digital (CSD) y a sellar comprobantes por su cuenta.
2. Revisar y redactar los avisos de privacidad: el de los usuarios de la plataforma y el contrato de encargo para los datos de terceros que trata por cuenta del cliente, incluidos los datos y el salario de sus empleados.
3. Fijar el procedimiento y el plazo de aviso ante un incidente de seguridad.
4. Contestar las preguntas abiertas de la sección 7.

## 2. Qué va a hacer el producto

- **Sellar.** Atlas ONE Financials armará y sellará cada CFDI con el CSD de la empresa cliente, y lo enviará ya sellado a un proveedor autorizado de certificación (PAC) que sólo lo timbra. El PAC nunca recibe la llave.
- **Custodiar.** La llave privada del CSD se guardará en un servicio de llaves de una nube externa (AWS KMS o Google Cloud KMS, por definir). En la opción preferida la llave se importa a ese servicio y firma ahí, sin salir nunca; en la de respaldo se guarda cifrada y sólo se descifra en memoria al sellar. La contraseña del certificado se descarta al darlo de alta. Detalle técnico: `docs/decisions/017-custodia-llaves-csd.md`.
- **Nunca pedir la e.firma.** La carga rechaza cualquier certificado que no sea de sello.
- **Emitir por orden del cliente o por eventos.** Además de las facturas que el usuario emita en pantalla, se emitirán comprobantes de forma automática a partir de eventos del punto de venta (Atlas ONE: factura de un ticket, factura global diaria) y de RRHH (HRFlow: recibos de nómina autorizados). La autorización del cliente tiene que cubrir esta emisión automática.
- **Cancelar.** Las cancelaciones se firman con el mismo CSD.
- **Conservar.** Los XML timbrados y acuses se conservan; la bitácora registra cada uso del certificado (quién, cuándo, qué documento, huella), nunca la llave.
- **Infraestructura.** La aplicación corre en Railway; el servicio de llaves está en una nube pública. Ambos pueden estar fuera de México **(sin verificar la región)**.
- **Proveedores de timbrado.** Dos PAC: uno primario y uno de contingencia (`docs/decisions/018-proveedor-de-timbrado.md`).

## 3. Marco identificado (lectura no dictaminada)

**Código Fiscal de la Federación**

- Art. 29, fr. II: el CSD es de uso exclusivo para expedir comprobantes y acredita su autoría; tramitarlo exige la e.firma.
- Art. 17-D: vigencia máxima de cuatro años.
- Art. 17-H, fr. I: el titular puede pedir la revocación; sólo él puede hacerlo.
- Art. 17-J: el titular debe actuar con diligencia, evitar el uso no autorizado y pedir la revocación ante cualquier riesgo; responde de las consecuencias de no hacerlo a tiempo.
- Art. 17-H Bis: restricción temporal del CSD; desde la reforma de noviembre de 2025 incluye causales nuevas, entre ellas comprobantes sin la clave de ingreso correcta (fr. XIII), que puede depender de la calidad del comprobante que genera el software.
- Art. 29 y 29 Bis: emisión por medios propios o por proveedores; regulación de los PAC. No se encontró regla ni formato para que un tercero que no es PAC custodie el CSD del contribuyente.
- Art. 30: conservación de la contabilidad y comprobantes por cinco años desde la declaración relacionada.
- Regla 2.7.2.7 de la RMF (escrito o manifiesto que el contribuyente entrega al PAC): **no se leyó**.

**Ley Federal de Protección de Datos Personales en Posesión de los Particulares (DOF 20-03-2025)**

- Autoridad: Secretaría Anticorrupción y Buen Gobierno (art. 2, fr. XV), que sustituyó al INAI.
- Persona encargada: trata datos por cuenta del responsable (art. 2, fr. XII). La comunicación entre responsable y encargado no es transferencia (art. 2, fr. XX).
- Datos financieros o patrimoniales: consentimiento expreso, salvo excepciones (art. 7); excepciones: disposición legal u obligaciones de una relación jurídica con el titular (art. 9, fr. I y IV).
- Datos sensibles: consentimiento expreso y por escrito (art. 8).
- Aviso de privacidad: contenido mínimo (art. 15) y aviso simplificado para medios electrónicos (art. 16).
- Medidas de seguridad proporcionales al riesgo y a la sensibilidad (art. 18).
- Vulneraciones que afecten de forma significativa derechos patrimoniales o morales: aviso inmediato al titular (art. 19). El texto no menciona aviso a la autoridad ni plazo en horas.
- Confidencialidad que sobrevive a la relación (art. 20).
- Cancelación de datos y sus excepciones por disposición legal u obligaciones fiscales (arts. 24, 25 y 33).
- Indemnización por daño causado por el responsable o la persona encargada (art. 53); infracciones y multas (arts. 58 y 59); delito por vulneración con ánimo de lucro (art. 62).
- Reglamento: la ley remite a uno; no se verificó si a noviembre de 2026 existe uno nuevo o si sigue aplicando el de 2011 en lo que no se oponga.

## 4. Contrato de custodia del CSD: qué revisar

1. **Forma jurídica de la autorización.** ¿Basta aceptar términos de servicio con evidencia electrónica (usuario, fecha, IP, versión del texto), o conviene un mandato o comisión mercantil? ¿Se necesita firma autógrafa o con e.firma del representante legal?
2. **Facultades de quien carga.** Cómo acreditar que quien sube el certificado es el titular o un representante con facultades.
3. **Emisión automática.** Que la autorización cubra la emisión disparada por eventos de otros sistemas del cliente (punto de venta, nómina), no sólo la emisión manual.
4. **Relación con el PAC.** Si el contribuyente debe firmar algo frente al PAC (regla 2.7.2.7 u otra) cuando el PAC se integra a través de Atlas, y quién lo recaba.
5. **Responsabilidad.** Cómo se reparte frente al cliente un comprobante emitido por error del software, uno emitido por un acceso indebido, y una restricción del CSD derivada de datos mal generados.
6. **Fin de la relación.** Exportación de XML, plazo de conservación posterior y borrado del certificado.

## 5. Cláusulas sugeridas (propuestas de trabajo)

| # | Cláusula | Contenido propuesto |
|---|---|---|
| 1 | Declaración de titularidad | Quien carga el CSD declara ser el titular o su representante con facultades suficientes, y que el certificado es un CSD y no una e.firma |
| 2 | **Alcance de uso del sello** | El cliente instruye a Atlas a usar el CSD **sólo** para sellar los comprobantes y firmar las cancelaciones que el cliente ordene desde la plataforma, o que resulten de reglas de emisión que el cliente haya activado (punto de venta, factura global, nómina). Cualquier otro uso queda prohibido. Atlas no usará el CSD para fines propios ni lo entregará a terceros, salvo al servicio de llaves que lo resguarda |
| 3 | No e.firma | Atlas no pide, no recibe y no guarda la e.firma; el cliente se obliga a no entregarla |
| 4 | Medidas de seguridad | Descripción en términos generales de la custodia (servicio de llaves externo, bitácora de uso, acceso restringido), sin prometer certificaciones que no existan. Atlas no es PAC ni está supervisado por el SAT; el PAC sí |
| 5 | **Aviso inmediato ante incidente** | Ante sospecha razonable de uso no autorizado o exposición del CSD, Atlas avisa al cliente por el canal pactado en un plazo máximo de **[plazo a fijar por el abogado; propuesta de trabajo: 24 horas]**, con: qué ocurrió, certificados afectados, ventana de tiempo, comprobantes emitidos o cancelados en esa ventana y la recomendación de revocar. Atlas pausa la emisión de inmediato. El aviso permite al cliente cumplir el art. 17-J |
| 6 | Obligaciones del cliente | Revocar el CSD ante sospecha; mantener vigente su certificado; proteger sus credenciales de acceso y usar el segundo factor; avisar a Atlas si revoca o cambia el certificado |
| 7 | **Revocación por el cliente** | El cliente puede retirar la autorización en cualquier momento, desde la plataforma o por escrito. Al hacerlo, Atlas deja de sellar y borra el material del CSD en un plazo de **[plazo]**. Retirar la autorización no revoca el certificado ante el SAT: eso sólo lo hace el cliente |
| 8 | Borrado | Al terminar el contrato, al reemplazar el certificado, al vencer o a petición. El borrado vuelve inútil la copia cifrada que quede en respaldos. Se conservan el certificado público (`.cer`) y la bitácora como evidencia |
| 9 | Subencargados | Lista de proveedores que tratan datos o resguardan el CSD (nube de la aplicación, servicio de llaves, PAC), su país y su función; aviso previo de cambios |
| 10 | **Responsabilidad** | Responsabilidad fiscal por lo emitido: del contribuyente, frente al SAT. Responsabilidad de Atlas frente al cliente: por incumplir el contrato o por negligencia en la custodia; límites y exclusiones **[a definir por el abogado]**. Tratamiento de errores del software en el contenido del comprobante |
| 11 | Bitácora | El cliente puede consultar la bitácora de uso de su certificado; plazo de retención **[a definir]** |
| 12 | Conservación y salida | Los XML se conservan durante el contrato; antes de borrar, el cliente puede exportarlos todos. Plazo de conservación después de la baja **[a definir]** |
| 13 | Confidencialidad | Obligación de confidencialidad del personal de Atlas que sobrevive al contrato |

## 6. Aviso de privacidad y datos de empleados

### Dos papeles distintos

- **Responsable** de los datos de los usuarios de la plataforma (dueños, administradores, contadores, representante legal): necesita su propio aviso de privacidad (art. 15) y aviso simplificado al registrarse (art. 16).
- **Encargado** de los datos que trata por cuenta del cliente: clientes y proveedores en los CFDI, y empleados en los recibos de nómina. Aquí el responsable es el cliente; Atlas necesita un contrato de encargo y el cliente, su propio aviso frente a sus empleados y clientes.

### Datos de empleados que pasarán por Financials

Nombre, RFC, CURP, número de seguridad social, código postal fiscal, fecha de ingreso, tipo de contrato y régimen, puesto, salario diario y salario diario integrado, percepciones, deducciones, incapacidades, y en su caso cuotas sindicales o pensión alimenticia. Llegan desde HRFlow por un evento firmado y quedan en el XML timbrado, que debe conservarse.

Puntos a revisar:

- **Salario.** Es dato financiero o patrimonial: consentimiento expreso (art. 7), salvo excepciones. La obligación legal del patrón de emitir el recibo (art. 9, fr. I) y la relación laboral (art. 9, fr. IV) parecen cubrir el tratamiento, pero la base de legitimación es del patrón y debe confirmarse.
- **Datos sensibles por inferencia.** Incapacidades pueden revelar salud; cuotas sindicales, afiliación. Propuesta técnica: tratar todo el módulo de nómina con medidas de datos sensibles (cifrado, acceso por rol, bitácora de consulta). ¿Cambia algo en el aviso o en el consentimiento?
- **HRFlow.** La auditoría del 25-11-2026 encontró que HRFlow no cifra campos ni registra quién consulta datos de empleados. Si la misma empresa opera HRFlow y Financials, ¿cómo se describen los dos tratamientos y el flujo entre ellos?
- **Solicitudes de cancelación (ARCO).** Un empleado que pide borrar su recibo: el XML debe conservarse por obligación fiscal (arts. 25 y 33). Como encargado, Atlas canaliza la solicitud al patrón.
- **Datos fuera de México.** Nube de la aplicación y servicio de llaves en el extranjero: no es transferencia hacia encargados, pero ¿debe declararse y cubrirse por contrato?

### Elementos mínimos propuestos para el aviso de los usuarios

Identidad y domicilio del responsable; datos tratados (identificación, contacto, credenciales, datos fiscales de la empresa, certificado de sello); finalidades primarias (operar la cuenta, emitir y conservar comprobantes, seguridad y bitácora) y secundarias, si las hay; subencargados y su país; medios para ejercer derechos ARCO y para revocar el consentimiento; cómo se avisan los cambios.

## 7. Preguntas abiertas

1. ¿Qué forma jurídica conviene para la autorización de uso del CSD y qué firma requiere?
2. ¿Existe en la RMF 2026 un escrito o manifiesto que el contribuyente deba firmar para el PAC (regla 2.7.2.7 u otra) y quién lo recaba cuando el PAC se integra por Atlas?
3. ¿Plazo concreto para avisar al cliente de un incidente con su CSD? ¿Conviene comprometer horas?
4. ¿Debe Atlas avisar a la Secretaría Anticorrupción y Buen Gobierno ante una vulneración, aunque la ley sólo mencione al titular? ¿Y a los empleados del cliente si se exponen recibos de nómina, o eso le toca al cliente?
5. ¿El CSD y su llave son datos personales cuando el titular es persona física con actividad empresarial? ¿Cambia el tratamiento?
6. ¿Hay un nuevo Reglamento de la LFPDPPP a noviembre de 2026, o sigue aplicando el de 2011? ¿Qué obligaciones del encargado contiene?
7. ¿Qué límite de responsabilidad es razonable y defendible frente a un daño por uso indebido del CSD? ¿Conviene un seguro de responsabilidad cibernética?
8. ¿Cómo se reparte la responsabilidad si un error del software en un comprobante contribuye a una restricción del CSD (art. 17-H Bis, fr. XIII)?
9. ¿Cuánto tiempo conservar la bitácora de uso del certificado, frente a la prescripción fiscal, civil y mercantil?
10. ¿Cuánto tiempo conservar los XML después de la baja del cliente, y cómo se documenta la entrega?
11. ¿Qué exigir por contrato al PAC (confidencialidad, no devolver llaves por API, notificación de incidentes, subencargo) y al servicio de llaves?
12. Para los recibos de nómina: ¿el patrón necesita consentimiento expreso del empleado para tratar su salario en una plataforma de un tercero, o basta la excepción legal?
13. ¿Hay delitos fiscales o informáticos aplicables al uso indebido de un CSD ajeno que deban considerarse en el contrato o en el procedimiento de incidente?

## 8. Material de apoyo

- `docs/decisions/017-custodia-llaves-csd.md`: diseño de custodia, bitácora, rotación y procedimiento de incidente.
- `docs/decisions/018-proveedor-de-timbrado.md`: relación con los PAC.
- `docs/financials/09_MEGAPLAN_CFDI.md`: plan completo.
- Notas de investigación (carpeta local, fuera de git, se entregan por separado): `research_notes/Timbrado CFDI y conexión Atlas/seguridad_csd_y_legal.md`, secciones 5, 7 y 9.
