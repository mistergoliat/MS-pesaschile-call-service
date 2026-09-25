# ADR 0002 — Llamadas salientes, sólo a Goli y con guardarraíles

- **Estado:** propuesto (pendiente de aprobación de Joaquín)
- **Fecha:** 2026-09-25
- **Autor:** Atlas (agente)
- **Repo:** `MS-pesaschile-call-service`
- **Relacionado:** ADR 0001 (pipeline único, local-first). **Enmienda** la §"Fuera de alcance" de la v1 del roadmap, que excluía llamadas salientes y SIP.

## Contexto

El repo ya implementa llamadas salientes por SIP (`app/providers/livekit_sip.py`: crea room + `CreateSIPParticipant` con `LIVEKIT_SIP_TRUNK_ID`) y las bloquea salvo hacia `ALLOWED_TEST_NUMBER`. Está apagado porque el troncal no está configurado. El README y el roadmap v1 las dejaban explícitamente fuera de alcance.

El dueño del proyecto pidió lo contrario:

> *"si existe una urgencia, me puedas llamar al teléfono y lo discutimos"*

Es una capacidad nueva del producto, no un detalle de implementación, y habilita la acción más riesgosa del ecosistema: **un sistema autónomo que puede marcar un teléfono**.

## Decisión

Se incorporan las llamadas salientes al alcance del piloto, con estas condiciones:

1. **Destino único: Goli.** La allowlist tiene exactamente un número. No se llama a clientes en esta fase.
2. **Severidad gateada.** Sólo `P0`/`P1` timbran; `P2` se queda en Discord.
3. **Disparadores deterministas.** Las condiciones que llaman son observables (health check, proceso PM2 muerto, disco, swap, host sin responder). **El criterio del agente ("esto me parece importante") no dispara una llamada.**
4. **Apagado por default.** `OUTBOUND_CALLS_ENABLED=false`: sin la variable, el endpoint responde 403 y no marca.
5. **Cupos y ventanas.** Máximo diario, una llamada en curso, dedupe por incidente, horas de silencio.
6. **Todo auditado.** Cada llamada queda como sesión con transcripción y resumen; cada decisión de no llamar, como evento.
7. **Discord como respaldo.** La llamada amplifica el aviso; nunca es la única señal.
8. **El que avisa no vive dentro de lo que vigila.** El worker de llamadas no corre en la instancia de producción.

Transporte: `pstn` (troncal SIP de Twilio/Telnyx/Plivo, ~US$0,07/min a móvil chileno) como default; `whatsapp` (Meta SIP, `wa.meta.vc`) evaluado después. Intercambiables por `OUTBOUND_TRANSPORT`.

## Alternativas consideradas

| alternativa | a favor | en contra | veredicto |
|---|---|---|---|
| **No hacerlo** (mantener la exclusión) | riesgo cero | dejaría el canal de urgencia en texto, que es exactamente lo que se pidió mejorar | no — la instrucción es explícita |
| **Sólo Discord voz** como canal de voz | gratis, ya funciona | no sirve como alerta: nadie está escuchando un canal de voz a las 3 a.m. | complementa, no sustituye |
| **WhatsApp calling primero** | usa el número que ya existe; timbra en el celular | requiere permiso previo y caduca a los 7 días; cupos por 24 h; costo de Meta sin confirmar | **segunda opción** |
| **PSTN por troncal SIP primero** | timbra siempre, sin permisos ni apps; costo conocido (~US$0,07/min) | hay que contratar y configurar un troncal; costo por minuto | **default propuesto** |
| **Que el LLM decida la urgencia** | reacciona a casos que ninguna regla cubre | un falso positivo a las 3 a.m. quema la confianza y el canal se apaga | no en v1 |
| **Llamar sin allowlist** | — | un sistema autónomo que marca cualquier número es un generador de llamadas no deseadas esperando a ocurrir | no |

## Consecuencias

**A favor:** existe un canal que de verdad despierta a alguien cuando producción se cae; el costo es despreciable a este volumen (~US$7/mes en el peor caso razonable); la auditoría de llamadas ya está resuelta por el modelo de sesiones existente; y la capacidad que el repo ya tenía escrita (`livekit_sip.py`) deja de estar muerta.

**En contra / a vigilar:**
- Aparece la primera acción del ecosistema con **efecto externo e irreversible**: una vez que suena el teléfono, ya no se puede deshacer. Todo el diseño de guardarraíles existe por esto.
- Hay una **dependencia nueva de terceros** (proveedor telefónico) que hoy no existe en el stack.
- La disponibilidad del PC pasa a ser parte del camino crítico de alerta mientras el piloto viva ahí.
- **Pendiente de verificar antes de implementar:** costo por minuto de Meta para WhatsApp calling; costo y disponibilidad del SIP de LiveKit Cloud; latencia real de *setup* del troncal; y si el troncal elegido puede usar un número chileno como caller ID.

## Lo que NO cambia

- El pipeline único y el STT/TTS local del ADR 0001.
- La exclusión de WhatsApp/Meta real del piloto (la integración existente queda intacta detrás de su flag).
- La exclusión de tocar el CRM o el catálogo.
- La instancia de producción: sigue siendo **read-only** y no recibe este servicio.
