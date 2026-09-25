# Piloto de voz sobre call-service — Roadmap

> Autor: **Atlas** (agente) · Fecha: **2026-09-25** · Estado: **propuesta para revisión de Joaquín**
> Base: `MS-pesaschile-call-service`, rama `main` @ `62ee026` (2026-07-14).
> Nada de este roadmap está implementado. Este documento, `ARQUITECTURA.md` y los ADR 0001/0002 son el entregable de la primera iteración.

## Objetivo

Convertir `call-service` en un canal de voz usable **primero por nosotros** y después por clientes, con tres metas concretas:

1. **Corto plazo:** poder hablar por voz con Atlas, desde el PC, sin depender de WhatsApp ni de Meta.
2. **Canal de urgencia:** que Atlas **me llame al teléfono** cuando algo se rompe, y discutirlo hablando en vez de leerlo (ADR 0002).
3. **Mediano plazo:** que ese mismo pipeline sea la base de la atención de voz a clientes, sin reescribirlo.

La primera meta es además la prueba de cómo desarrollo: PRs chicos, revisables, con evidencia y con tests.

## Estado de partida (verificado, no inferido)

Lo que el código hace **hoy**:

- **`OPENAI_API_KEY` está vacía** en el `.env`. Por lo tanto `build_stt()`, `build_tts()` (`app/core/livekit_voice_models.py`) y `ensure_configured()` (`app/core/agent.py`) **levantan `AppError` 503**. **Ninguno de los dos pipelines de voz del repo puede correr hoy.**
- Hay **dos pipelines paralelos**, con proveedores distintos, haciendo lo mismo:
  - **A — LiveKit:** `app/core/livekit_agent_worker.py` → room + agente con `AgentSession(llm=DeepSeek, stt=OpenAI, tts=OpenAI)`. Es el camino de WhatsApp calling.
  - **B — OpenAI Realtime:** `app/core/agent.py` + `app/api/demo.py` → el navegador negocia SDP contra `api.openai.com/v1/realtime/calls` con una clave efímera proxeada por el servidor.
- El provider `local_webrtc` (`app/providers/local_webrtc.py`) **no transporta media**: guarda estados en un `dict`. El WebRTC real lo hace el navegador contra OpenAI. El nombre promete más de lo que entrega.
- **Llamadas salientes: el código ya existe y está apagado.** `app/providers/livekit_sip.py` crea la room y llama a `CreateSIPParticipant` con `LIVEKIT_SIP_TRUNK_ID`, y `compliance_service.validate_outbound_test_call()` exige E.164 + lista de supresión + destino igual a `ALLOWED_TEST_NUMBER`. Falta sólo el troncal.
- **36 tests** en 6 archivos, y **cero CI**: no existe `.github/`. Nada los corre automáticamente.
- No hay `AGENTS.md`, `CONTRIBUTING.md`, `docs/` ni ADRs. La intención arquitectónica vive sólo en el README y en el código.
- `LIVEKIT_*` y `DEEPSEEK_API_KEY` **sí** están configuradas. Las credenciales de Meta también, pero `WHATSAPP_CALLING_ENABLED` no está definida (default `false`) y la allowlist está vacía.

## Roadmap por fases

Cada fase es **un PR independiente y revisable**. Las fases 1–4 no necesitan gastar un peso en APIs de voz.

### Fase 0 — Propuesta (este PR)
- `docs/voice-pilot/ROADMAP.md`, `docs/voice-pilot/ARQUITECTURA.md`, `docs/adr/0001-pipeline-unico-local-first.md`, `docs/adr/0002-llamadas-salientes-con-guardarrailes.md`.
- **Criterio de aceptación:** Joaquín aprueba o corrige la dirección antes de que se escriba código.

### Fase 1 — CI (PR chico, alto valor)
- `.github/workflows/ci.yml`: `pytest` + `ruff` en cada PR.
- **Por qué primero:** un flujo de "abro PRs para que las revises" sin gate automático deja la revisión a ojo. Los 36 tests ya existen y hoy nadie los ejecuta.
- **Criterio de aceptación:** el workflow corre en verde sobre `main` sin tocar una línea de código de aplicación.

### Fase 2 — Capa de habla intercambiable (el desbloqueo real)
- `app/core/speech/` con implementaciones propias de `stt.STT` y `tts.TTS` de LiveKit:
  - `faster_whisper_stt.py` → `faster-whisper` local, envuelto en `stt.StreamAdapter(stt, vad_stream)` porque Whisper **no** es streaming (documentado por LiveKit).
  - `edge_tts_tts.py` → `edge-tts` (gratis), envuelto en el `tts.StreamAdapter` de LiveKit.
- Config nueva: `STT_PROVIDER=local|openai`, `TTS_PROVIDER=local|openai`. **El default sigue siendo lo que ya había**; el cambio es opt-in y se revierte con una variable.
- Un benchmark de latencia medido, no estimado (ver `ARQUITECTURA.md` §4).
- **Criterio de aceptación:** el worker LiveKit arranca y conversa **sin `OPENAI_API_KEY`**, con tests que cubran los adaptadores sin red.
- **Prerrequisito de la fase 6:** sin esto, la llamada de urgencia depende de una credencial de OpenAI que hoy no existe.

### Fase 3 — Un solo pipeline
- Apuntar el demo del navegador (`app/static/demo.html`) a la **room de LiveKit** en vez de a OpenAI Realtime.
- Decidir el destino de `RealtimeVoiceAgent` y de `local_webrtc`: implementarlo de verdad o retirarlo y renombrarlo. **No dejarlo con el nombre de algo que no hace.**
- **Criterio de aceptación:** `grep -r "api.openai.com/v1/realtime"` en el repo da cero, o el camino Realtime queda explícitamente detrás de un flag y documentado como alternativa.

### Fase 4 — El cerebro: bridge a Atlas
- Que la voz sea oídos y boca; **el cerebro sigue siendo uno solo**. Un adapter que permita al agente consultar a Atlas (KB, estado de repos, hallazgos) en lugar de ser un chat DeepSeek aislado.
- Es lo que hace útil una llamada de urgencia: del otro lado hay alguien que sabe qué estaba pasando.
- **Criterio de aceptación:** en una conversación de voz se puede preguntar algo que sólo existe en la knowledge base de Atlas y la respuesta es correcta.

### Fase 5 — Llamada saliente de urgencia (ADR 0002)
Depende de la fase 2, no de la 3 ni la 4. Se puede adelantar si se quiere tener el canal de urgencia antes.

- **5a — Traslado del test existente a la API real:** `POST /calls/outbound` (severidad, razón, contexto, `dedupe_key`, `expires_at`) reemplazando el uso de `/calls/test`, reusando el modelo de sesión y el registro de eventos que ya existen.
- **5b — `app/services/outbound_policy.py`:** allowlist (un solo número), cupo diario, una en curso, dedupe, horas de silencio, severidad mínima, kill switch. Tests con tabla de casos — es la parte que más importa testear.
- **5c — Troncal real:** `CreateSIPOutboundTrunk` con `destination_country="CL"` contra Twilio/Telnyx/Plivo; llamada de prueba al número propio; medir *setup* y latencia real del turno.
- **5d — Disparadores deterministas:** health check, proceso PM2 muerto, disco, swap, host sin responder. **Sin criterio del agente.** Respaldo obligatorio en Discord.
- **5e — (evaluar después) transporte `whatsapp`** vía Meta SIP, `wa.meta.vc`.
- **Criterio de aceptación:** ante un fallo simulado en un entorno controlado, suena el teléfono, el agente explica qué pasó y responde preguntas; y con `OUTBOUND_CALLS_ENABLED=false` no marca absolutamente nada.

### Fase 6 — Endurecer para clientes (aún no)
- Costo por minuto medido, retención de transcripciones, PII y consentimiento (ya existen `compliance_service` y el modelo `suppression`), límites de duración, observabilidad, y **dónde corre** en producción.
- **No se toca** hasta que las fases 1–4 estén cerradas. Las llamadas salientes **a clientes** son fase 6 y necesitan su propia decisión explícita, con consentimiento y normativa de por medio.

## Fuera de alcance (decidido)

- ~~**Llamadas salientes y SIP.** El README ya las deja fuera y `LIVEKIT_SIP_TRUNK_ID` está vacía. Se mantiene.~~
  **Revocado el 2026-09-25 por instrucción explícita del dueño del proyecto** ("si existe una urgencia, me puedas llamar al teléfono"). Pasa a la fase 5, con destino único y los guardarraíles del ADR 0002. El resto del roadmap no cambia.
- **WhatsApp/Meta real.** El piloto no depende de Meta. La integración ya existe y queda intacta detrás de su flag.
- **Tocar el CRM o el catálogo.** La voz se desarrolla contra endpoints propios; la integración comercial viene después de la fase 6.
- **Llamar a clientes.** Sin excepción en esta etapa.

## Dónde corre el piloto (decisión con evidencia)

**En el PC de Goli, con `docker compose` local. No en la instancia EC2 de producción.**

Ver `atlas/infra-produccion.md` (verificación read-only del 2026-09-25): la instancia es una **t3.medium con 2 vCPU, 3.835 MB de RAM y cero swap**, ya sostiene nginx + MariaDB + 6 procesos PM2, tiene el disco al 76% y **hoy tiene 3 de 8 procesos caídos**. Instalar ahí un agente de voz en tiempo real —que necesita CPU continua y memoria— repetiría el incidente del 16-sep, esta vez por diseño.

**La fase 5 agrega un requisito nuevo: disponibilidad.** Un canal de alerta que sólo funciona con el PC encendido no vigila producción de verdad. Mientras el piloto viva en el PC, el PC es parte del camino crítico de alerta y hay que tratarlo como tal. Cuando la llamada de urgencia deje de ser experimento, va a **una instancia propia y chica, separada de producción**, y el disparador vive fuera de la instancia vigilada.
