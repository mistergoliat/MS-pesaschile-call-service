# Voice Agent Service

Microservicio FastAPI para una prueba real de llamada entrante de WhatsApp con LiveKit, DeepSeek y OpenAI STT/TTS.

## Objetivo de esta iteracion

Esta iteracion deja listo el flujo:

```text
WhatsApp personal
-> llama a +56 9 2175 7996
-> Meta envía webhook calls con call_id y SDP offer
-> voice-agent-service valida la firma o el secreto interno
-> acepta la llamada con LiveKit AcceptWhatsAppCall
-> LiveKit crea la room
-> se despacha el agente whatsapp-agent
-> el agente escucha, transcribe y responde
-> DeepSeek genera el texto
-> OpenAI genera STT/TTS
-> el usuario escucha la IA
```

No se renta ningun numero.
No se usa SIP.
No se implementan llamadas salientes.
No se toca el catalogo, CRM, cotizaciones, tools comerciales ni el worker autonomo.

## Que queda funcionando

- `GET /webhooks/meta/whatsapp-calling` para verificacion de Meta.
- `POST /webhooks/meta/whatsapp-calling` para eventos directos de Meta o forward interno.
- `GET /diagnostics/whatsapp-calling` para validar readiness sin exponer secretos.
- Worker LiveKit con DeepSeek como LLM y OpenAI solo para STT/TTS.
- Persistencia de sesiones y eventos de llamada.
- Mensajeria existente y endpoints previos sin cambios de comportamiento.

## Variables de entorno

### Requeridas para WhatsApp calling

```bash
META_WHATSAPP_ACCESS_TOKEN=
META_WHATSAPP_PHONE_NUMBER_ID=1030337916832905
META_WHATSAPP_APP_SECRET=
META_WHATSAPP_VERIFY_TOKEN=
META_WHATSAPP_CLOUD_API_VERSION=v24.0

LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
LIVEKIT_AGENT_NAME=whatsapp-agent

DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat

OPENAI_API_KEY=
OPENAI_INPUT_TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
OPENAI_TTS_MODEL=gpt-4o-mini-tts
OPENAI_TTS_VOICE=ash

WHATSAPP_CALLING_ENABLED=false
WHATSAPP_CALLING_TEST_MODE=true
WHATSAPP_CALLING_ALLOWED_CALLERS=
WHATSAPP_CALLING_MAX_DURATION_SECONDS=120

INTERNAL_WEBHOOK_SECRET=
PUBLIC_BASE_URL=https://tu-dominio-publico
```

### Notas

- `WHATSAPP_CALLING_ALLOWED_CALLERS` acepta numeros E.164 separados por comas.
- `WHATSAPP_CALLING_ENABLED` debe quedar en `true` para procesar llamadas reales.
- `WHATSAPP_CALLING_TEST_MODE=true` limita la entrada a los numeros permitidos.
- `PUBLIC_BASE_URL` debe apuntar a la URL publica real del backend.
- La URL publica del webhook es:

```text
${PUBLIC_BASE_URL}/webhooks/meta/whatsapp-calling
```

## Docker

Levanta el backend y el worker LiveKit con:

```bash
docker compose --profile livekit up -d --build
```

Servicios esperados:

- FastAPI en `http://localhost:8000`
- Worker LiveKit ejecutando `python -m app.core.livekit_agent_worker`

El servicio `app` tiene healthcheck en `/health` y `livekit-agent` arranca cuando `app` esta healthy.

## Endpoints relevantes

- `GET /health`
- `GET /diagnostics/whatsapp-calling`
- `GET /webhooks/meta/whatsapp-calling`
- `POST /webhooks/meta/whatsapp-calling`
- `POST /calls/end`
- `GET /calls/{call_id}`
- `POST /calls/{call_id}/events`
- `GET /docs`

## Como enrutar calls sin romper messages

El endpoint de WhatsApp calling ya acepta dos modos:

- Modo directo Meta:
  - enviar `X-Hub-Signature-256`
  - el backend lee el body crudo
  - valida HMAC SHA-256 con `META_WHATSAPP_APP_SECRET`
  - luego parsea JSON

- Modo forward interno:
  - enviar `X-Internal-Webhook-Secret`
  - el valor debe coincidir con `INTERNAL_WEBHOOK_SECRET`
  - no se aceptan requests sin firma Meta ni secreto interno

Esto permite que el webhook actual de mensajes reenvie eventos de calls a:

```text
POST /webhooks/meta/whatsapp-calling
```

sin alterar el manejo de messages.

## Configuracion exacta en Meta

1. Usa el numero empresarial existente `+56 9 2175 7996`.
2. No rentar ni provisionar otro numero en LiveKit.
3. Mantener SIP desactivado en Meta.
4. Suscribir el webhook a `calls`.
5. Configurar el callback URL publico:

```text
https://tu-dominio-publico/webhooks/meta/whatsapp-calling
```

6. Configurar `META_WHATSAPP_VERIFY_TOKEN` con el mismo valor en Meta y en `.env`.
7. Configurar `META_WHATSAPP_APP_SECRET`.
8. Configurar `META_WHATSAPP_ACCESS_TOKEN`.
9. Confirmar `META_WHATSAPP_PHONE_NUMBER_ID=1030337916832905`.
10. Usar Cloud API v24.0 salvo incompatibilidad comprobada.

### Firma del webhook

El backend valida `X-Hub-Signature-256` con HMAC SHA-256 sobre el body crudo usando `META_WHATSAPP_APP_SECRET`.

## Configuracion minima exacta en LiveKit

1. Proveer `LIVEKIT_URL`, `LIVEKIT_API_KEY` y `LIVEKIT_API_SECRET`.
2. No crear trunk SIP para esta prueba.
3. Mantener el worker con `LIVEKIT_AGENT_NAME=whatsapp-agent`.
4. No rentar ningun numero en LiveKit.
5. Permitir que el connector cree la room al aceptar la llamada inbound.

El request usa `AcceptWhatsAppCall` con `RoomAgentDispatch(agent_name="whatsapp-agent")`.

## Procedimiento de prueba real

1. Levanta el stack con Docker.
2. Verifica readiness:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/diagnostics/whatsapp-calling
```

3. En Meta, confirma que el webhook de `calls` esta suscrito y el callback responde `200`.
4. Desde un WhatsApp personal, llama al numero empresarial `+56 9 2175 7996`.
5. El webhook debe llegar a `POST /webhooks/meta/whatsapp-calling`.
6. El backend debe aceptar la llamada con LiveKit.
7. El worker debe unirse a la room como `whatsapp-agent`.
8. La voz de salida debe venir de OpenAI TTS.
9. Las respuestas deben ser generadas por DeepSeek.
10. La llamada debe cortar a los `120` segundos o al terminar el usuario.

## Troubleshooting

- `META_WHATSAPP_WEBHOOK_VERIFICATION_FAILED`
  - el verify token no coincide.

- `META_WHATSAPP_SIGNATURE_INVALID`
  - la firma `X-Hub-Signature-256` no coincide con el body crudo.

- `WEBHOOK_AUTH_REQUIRED`
  - faltan firma Meta e `X-Internal-Webhook-Secret`.

- `WHATSAPP_CALLING_DISABLED`
  - `WHATSAPP_CALLING_ENABLED` sigue en `false`.

- `META_WHATSAPP_CALLER_BLOCKED`
  - el caller no esta en `WHATSAPP_CALLING_ALLOWED_CALLERS` durante test mode.

- `META_WHATSAPP_PHONE_NUMBER_ID_MISMATCH`
  - el webhook trae un phone number id distinto al configurado.

- `META_WHATSAPP_SDP_MISSING`
  - el payload no trae SDP offer.

- `LIVEKIT_CALL_ACCEPT_FAILED`
  - revisar credenciales de LiveKit, token de Meta y conectividad del connector.

- `LIVEKIT_CALL_DISCONNECT_FAILED`
  - revisar que la llamada siga activa y que LiveKit acepte el disconnect.

- `OPENAI_NOT_CONFIGURED`
  - falta `OPENAI_API_KEY` para STT/TTS.

- `DEEPSEEK_NOT_CONFIGURED`
  - falta `DEEPSEEK_API_KEY` para el worker.

## Tests

Ejecutar:

```bash
pytest
```

La suite ya cubre:

- verificacion Meta valida e invalida;
- firma Meta valida e invalida;
- secreto interno valido e invalido;
- connect inbound;
- allowlist de callers;
- feature flag apagado;
- phone_number_id incorrecto;
- call_id faltante;
- SDP faltante;
- evento duplicado;
- idempotencia de sesion;
- AcceptWhatsAppCall invocado correctamente;
- error de LiveKit;
- terminate;
- DisconnectWhatsAppCall;
- diagnostics sin secretos;
- no regresion de endpoints existentes.

## Estado del flujo

Quedan fuera de esta iteracion:

- llamadas salientes;
- SIP;
- catalogo, CRM y cotizaciones;
- integracion con worker autonomo comercial.

