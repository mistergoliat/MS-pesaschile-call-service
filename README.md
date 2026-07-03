# Voice Agent Service

Microservicio modular para agentes de voz con FastAPI, Swagger/OpenAPI y una abstraccion de provider para evitar acoplar el core a Twilio, LiveKit, Meta o cualquier carrier especifico.

## Que resuelve

- Prueba local por navegador con `LocalWebRTCProvider` y una demo en `/demo`.
- Flujo de llamadas de prueba desacoplado via `VoiceProvider`.
- Preparacion para `LiveKitSIPProvider` con room + SIP outbound participant.
- Placeholder estructural para `MetaWhatsAppCallingProvider`.
- Persistencia de sesiones, eventos, transcript y resumen.
- Swagger UI en `/docs` y schema OpenAPI en `/openapi.json`.

## Arquitectura

```text
Voice Agent Service
   ->
VoiceProvider abstraction
   |- LocalWebRTCProvider
   |- LiveKitSIPProvider
   |- MetaWhatsAppCallingProvider
   |- TwilioProvider (futuro, no implementado)
   ->
Realtime Voice Agent
   ->
OpenAI Realtime API
   ->
CRM / HUB / Orchestrator futuro
```

El core maneja sesiones, eventos, transcript, resumen y guardrails. No sabe si el audio viene del navegador, de LiveKit SIP o de una futura API de llamadas.

## Por que no depende de Twilio

Twilio no es la base del sistema ni aparece en el core. Toda la logica pasa por la interfaz `VoiceProvider`, de modo que un adapter futuro de Twilio seria opcional y reemplazable. El flujo principal de este MVP esta pensado para:

1. Navegador/WebRTC sin carrier.
2. LiveKit + SIP trunk para llamadas reales autorizadas.
3. Placeholder para Meta WhatsApp Calling con consentimiento previo.

## Estructura

```text
voice-agent-service/
  app/
    api/
    core/
    db/
    models/
    providers/
    schemas/
    services/
    static/demo.html
    config.py
    main.py
  tests/
  Dockerfile
  docker-compose.yml
  requirements.txt
  .env.example
  README.md
```

## Variables de entorno

```bash
cp .env.example .env
```

Completa al menos:

- `OPENAI_API_KEY` para la demo real por navegador con OpenAI Realtime.
- `ALLOWED_TEST_NUMBER` con tu numero autorizado.
- `LIVEKIT_*` cuando quieras probar SIP outbound real.

## Como correr local

```bash
docker compose up --build
```

Si prefieres correr sin Docker:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Como probar

Health:

```bash
curl http://localhost:8000/health
```

Swagger UI:

```text
http://localhost:8000/docs
```

Demo browser:

```text
http://localhost:8000/demo
```

OpenAPI schema:

```text
http://localhost:8000/openapi.json
```

## Endpoints principales

- `GET /health`
- `GET /docs`
- `GET /openapi.json`
- `GET /demo`
- `POST /demo/session`
- `POST /demo/connect`
- `POST /demo/events`
- `POST /calls/test`
- `POST /calls/end`
- `GET /calls/{call_id}`
- `POST /webhooks/livekit`
- `POST /webhooks/meta/whatsapp-calling`

## Probar llamada local por navegador

1. Abre `/demo`.
2. Presiona `Iniciar sesion`.
3. Acepta permiso de microfono.
4. Si `OPENAI_API_KEY` esta configurada, el backend negociara el SDP con OpenAI Realtime y el navegador abrira la sesion WebRTC sin exponer la API key al cliente.
5. Los eventos del browser se guardan en `voice_call_events`.

Si no configuraste `OPENAI_API_KEY`, la sesion local igual se crea y queda trazabilidad, pero `POST /demo/connect` fallara con `OPENAI_NOT_CONFIGURED`.

## Probar llamada test con LiveKit

```bash
curl -X POST http://localhost:8000/calls/test \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "livekit",
    "to": "+569XXXXXXXX",
    "initial_message": "Hola, esta es una prueba tecnica autorizada."
  }'
```

Guardrails activos:

- Solo permite `provider=livekit` con `to == ALLOWED_TEST_NUMBER`.
- Bloquea numeros fuera de E.164.
- Bloquea numeros en suppression list.
- Bloquea llamadas masivas y cold calling por diseno.
- Rate limit maximo: `MAX_CALLS_PER_MINUTE`.

## Preparacion de LiveKit SIP

El provider crea una room e intenta crear un outbound SIP participant usando `LIVEKIT_SIP_TRUNK_ID`. Para completarlo en un entorno real necesitas:

1. Credenciales validas de LiveKit.
2. SIP trunk outbound ya configurado.
3. Un agente de voz unido a la room.
4. Ajustar webhooks/observabilidad segun tu infraestructura.

El proyecto deja esa base lista, pero no mete LiveKit como dependencia del core ni como unica ruta de ejecucion.

Para levantar tambien el worker del agente LiveKit en Docker Compose:

```bash
docker compose --profile livekit up --build
```

## Meta WhatsApp Calling

El archivo `app/providers/meta_whatsapp_calling.py` existe como placeholder seguro:

- deja el punto de extension para webhook de eventos;
- deja claro que hara falta consentimiento y permission workflow;
- devuelve error controlado `META_WHATSAPP_CALLING_NOT_IMPLEMENTED`.

No implementa llamadas reales todavia.

## Base de datos

SQLAlchemy usa SQLite para el MVP y el diseno es portable a PostgreSQL. Se crean estas tablas:

- `voice_call_sessions`
- `voice_call_events`
- `voice_call_permissions`
- `voice_suppression_list`

## Tests

```bash
pytest
```

Los tests cubren health, docs, OpenAPI, compliance, providers, eventos y rate limit.

## Limitaciones del MVP

- No hay Redis para rate limit distribuido.
- No hay migraciones versionadas; se usa bootstrap por metadata.
- La demo WebRTC del navegador depende de `OPENAI_API_KEY` para audio real.
- El join del agente a una room LiveKit esta preparado conceptualmente, pero una integracion completa de agentes y operacion en produccion requerira mas wiring.
- Meta WhatsApp Calling sigue como placeholder.

## Compliance

No usar este servicio para:

- prospeccion fria;
- autodialing;
- campanas masivas;
- llamadas sin consentimiento;
- listas de contactos.

Este MVP esta pensado solo para pruebas controladas y numeros autorizados.
