# Piloto de voz sobre call-service — Arquitectura

> Autor: **Atlas** (agente) · Fecha: **2026-09-25** · Estado: **propuesta para revisión**
> Ver `ROADMAP.md` para la secuencia de PRs y `docs/adr/` para las decisiones.

## 0. Enmienda de alcance (v2 de este documento)

La primera versión de este documento y de `ROADMAP.md` dejaban **las llamadas salientes y SIP fuera de alcance**, siguiendo al README del repo. **Esa exclusión queda revocada por decisión del dueño del proyecto (2026-09-25):**

> *"si existe una urgencia, me puedas llamar al teléfono y lo discutimos"*

No es un cambio de implementación: es un **cambio de alcance del producto**, y por eso se registra acá y en `docs/adr/0002`. El resto del documento original se mantiene; lo nuevo es la §6 (salientes) y la §7 (guardarraíles).

También queda aclarado el objetivo de "conversar": **Atlas debe responder con voz**, no sólo por texto. Eso es la §5.

## 1. Estado actual: dos stacks, ninguno ejecutable

```
        ┌──────────────── CAMINO A — LiveKit (el de WhatsApp) ────────────────┐
Meta ──►│ POST /webhooks/meta/whatsapp-calling  (HMAC o secreto interno)      │
        │        └─► AcceptWhatsAppCall (LiveKit) ─► room ─► dispatch agent   │
        │                                                    │               │
        │  app/core/livekit_agent_worker.py                  ▼               │
        │  AgentSession(llm=DeepSeek, stt=OpenAI, tts=OpenAI) ──► requiere    │
        │                                    OPENAI_API_KEY  ──► HOY VACÍA    │
        └────────────────────────────────────────────────────────────────────┘

        ┌──────────────── CAMINO B — OpenAI Realtime (el del navegador) ───────┐
Navegador ─►│ POST /demo/session  ─► provider "local_webrtc" (stub, sin media)│
            │ POST /demo/connect  ─► el servidor proxea SDP a                 │
            │     https://api.openai.com/v1/realtime/calls ──► requiere       │
            │                                    OPENAI_API_KEY  ──► HOY VACÍA│
            └────────────────────────────────────────────────────────────────┘
```

Los dos caminos terminan en el mismo bloqueo y **no comparten código de voz**. El camino B además se salta LiveKit por completo, aunque `LIVEKIT_*` esté configurado y el `docker-compose` levante un worker LiveKit.

**Y hay un tercer camino, ya escrito y sin usar: `app/providers/livekit_sip.py` implementa llamadas salientes por SIP** — crea la room, llama a `CreateSIPParticipant` con `LIVEKIT_SIP_TRUNK_ID` y exige que el destino sea `ALLOWED_TEST_NUMBER` (si no, `OUTBOUND_CALL_BLOCKED`). Está apagado sólo porque `LIVEKIT_SIP_TRUNK_ID` está vacía. **Esta es la pieza que el pedido de "llamarme si hay urgencia" convierte en central.**

**Consecuencia:** hoy `call-service` no puede sostener una conversación por ninguna de sus puertas.

## 2. Arquitectura objetivo

Una sola ruta de audio y una sola capa de política, con las piezas intercambiables por configuración.

```
 ENTRADA (transporte)         ORQUESTACIÓN            CEREBRO          HABLA
 ────────────────────         ────────────            ───────          ─────
 Navegador (WebRTC)  ─┐
 WhatsApp calling    ─┼─►  LiveKit room  ──►  AgentSession  ──►  LLM  ──►  TTS
 SIP / PSTN (saliente)─┘                       + VAD silero     (DeepSeek)   STT
                                               + turnos         + bridge     (StreamAdapter)
                                                                  a Atlas
                                                                     ▲
                                                                     │
 Hermes (Atlas) ──► POST /calls/outbound ──► capa de política ────────┘
   cron / regla                                  (§7)
```

Los eslabones quedan detrás de variables de entorno. Nada de lo que sigue obliga a reescribir el pipeline cuando se cambie una pieza:

| pieza | opciones | default propuesto |
|---|---|---|
| Transporte entrante | LiveKit (browser / WhatsApp / SIP) | **LiveKit** — el WhatsApp ya está construido encima |
| Transporte saliente | `pstn` (Twilio/Telnyx/Plivo) · `whatsapp` (Meta SIP) · `off` | **`off`** hasta la fase 6 |
| STT | `local` (faster-whisper) · `openai` · `groq` | **`local`** |
| TTS | `local` (edge-tts) · `openai` | **`local`** |
| LLM | DeepSeek (ya integrado) · otro OpenAI-compatible | **DeepSeek** (sin cambios) |
| Cerebro | chat aislado · **bridge a Atlas** | chat aislado ahora, bridge en fase 4 |
| Canales de aviso | Discord (texto) · Discord (voz) · llamada telefónica | **Discord texto** siempre; llamada sólo en P0/P1 |

## 3. La decisión técnica de fondo: STT/TTS locales

### Por qué

1. **Desbloquea el repo sin gastar**: `OPENAI_API_KEY` está vacía y el pipeline no arranca. Con STT/TTS locales, corre sin ninguna credencial de voz.
2. **Costo marginal cero**: para un canal de voz con clientes, el STT/TTS cloud se paga por minuto y escala con el uso. `faster-whisper` local y `edge-tts` no.
3. **Es un camino soportado, no un hack.** La documentación de LiveKit (`docs.livekit.io/agents/models/stt/`) trata explícitamente el caso: Whisper no es streaming, así que se envuelve con `StreamAdapter` + VAD para que el VAD decida dónde termina el habla. Existe el mismo patrón para TTS (`livekit/agents/tts/stream_adapter.py`).
4. **Independencia de proveedor.** El mismo diseño acepta después un STT cloud rápido sin tocar la orquestación.

**Y ahora es además un requisito de la llamada telefónica:** sin STT/TTS locales, la llamada de urgencia depende de una credencial de OpenAI que hoy no existe. La fase 2 deja de ser una optimización y pasa a ser **prerrequisito de la fase 6**.

### Cómo

```python
# STT (no streaming: Whisper procesa por segmentos)
class FasterWhisperSTT(stt.STT):
    def __init__(self, model: str = "base", ...):
        super().__init__(capabilities=stt.STTCapabilities(
            streaming=False, interim_results=False))
    async def _recognize_impl(self, buffer, *, language=None) -> stt.SpeechEvent:
        ...  # buffer -> numpy -> model.transcribe() -> SpeechEvent(FINAL_TRANSCRIPT)

# en el worker: el VAD marca el fin del habla y recién ahí se transcribe
stt = stt.StreamAdapter(stt=FasterWhisperSTT(...), vad=vad_stream)
```

```python
# TTS: edge-tts devuelve MP3; se emiten AudioFrames PCM al emitter de LiveKit
class EdgeTTS(tts.TTS):
    def __init__(self, voice: str = "es-CL-LorenzoNeural"):
        super().__init__(capabilities=tts.TTSCapabilities(streaming=False),
                         sample_rate=24000, num_channels=1)
    def synthesize(self, text, *, conn_options) -> ChunkedStream: ...
```

Ambos adaptadores deben cumplir el contrato de la versión pineada: **`livekit-agents==1.5.12`**. Si la firma difiere en esa versión, se ajusta contra el paquete instalado — no contra la documentación.

### Alternativas evaluadas

| alternativa | a favor | en contra | veredicto |
|---|---|---|---|
| Plugin de terceros (`local-livekit-plugins`: FasterWhisperSTT + PiperTTS) | ya escrito, probado | dependencia no oficial, que hay que seguir; acopla nuestro roadmap al suyo | **spike de 1 hora antes de escribir el nuestro** |
| `PiperTTS` en vez de edge-tts | 100% offline, sin red | hay que gestionar modelos `.onnx` por voz y por idioma; más piezas | candidato para producción |
| `edge-tts` | gratis, ya probado en este PC, voz chilena disponible | requiere red (Microsoft), no apto para un servicio que deba ser autónomo | **piloto sí, producción a revisar** |
| Mantener OpenAI para STT/TTS | cero desarrollo | cuesta por minuto y **hoy está bloqueado** por la key vacía | no |

## 4. Presupuesto de latencia (medido, no estimado)

Medido en este PC (CPU, sin GPU) con el modelo `base` en `int8`, ya cargado en memoria:

- **16,2 s de audio → 5,1 s de proceso** ⇒ ≈ 0,31 × tiempo real. Una intervención de 4 s se transcribe en ~1,2 s.
- Más el silencio que el VAD debe confirmar antes de cortar (~0,5–1 s) y el TTS (~0,3–0,6 s): **≈ 2–2,5 s por turno**.
- El modelo `small` transcribe mejor en español pero es ~2–3 × más lento ⇒ **≈ 3,5–4,5 s por turno**, que ya se siente lento.
- En una llamada telefónica hay que sumar el *setup* del troncal (SIP INVITE + ring) y la latencia de red a la región del proveedor. Eso **no** está medido y no se debe prometer: se mide en la fase 6 con el troncal real.

**Conclusión:** el piloto arranca con `base` y un benchmark que mida el turno completo de punta a punta. Si la latencia no alcanza, las salidas son (a) un VAD con ventana de silencio más corta, (b) un STT cloud rápido sólo para producción, o (c) GPU — y ninguna de las tres obliga a rediseñar: la capa ya quedó intercambiable por configuración.

## 5. Los canales de conversación con Atlas (y por qué son dos)

"Hablar con voz" y "que me llame" son dos necesidades distintas y conviene no mezclarlas:

| canal | para qué | costo | límites | estado |
|---|---|---|---|---|
| **Discord, canal de voz** | conversar, pensar en voz alta, revisar código, discutir un PR | $0 (es transporte de Discord) | ninguno relevante | **ya funciona** (STT local + TTS `es-CL-LorenzoNeural`) |
| **Llamada telefónica** | sólo urgencia: algo se rompió y hay que decidir ya | ~US$0,07/min al móvil chileno | permiso previo, cupos diarios, horas de silencio (§7) | fase 6 |

**Decisión:** el día a día va por Discord voz; el teléfono queda reservado para urgencia. No es una limitación técnica — es que un canal que timbra tiene que ser escaso, o deja de significar algo. Y en Discord ya está resuelto y gratis.

## 6. Llamadas salientes (el canal de urgencia)

### 6.1 Dos transportes, una interfaz

El repo ya sabe llamar por SIP (`livekit_sip.py`). Lo que falta es **el troncal**, y hay dos caminos reales:

**A — PSTN por troncal SIP (Twilio / Telnyx / Plivo).** Timbra cualquier teléfono, sin permiso previo de nadie.

- Configuración: `CreateSIPOutboundTrunk` con `address` (`<trunk>.pstn.twilio.com`, `sip.telnyx.com`, `<id>.zt.plivo.com`), `numbers`, `auth_username`/`auth_password`, y **`destination_country="CL"`** para fijar el origen en la región del destino.
- Costo a **móvil chileno (+56 9)**: Twilio **US$0,0746/min** (Programmable Voice) o **US$0,0706/min** (Elastic SIP Trunking); Plivo **US$0,0730/min**. Números locales CL aparte (~US$7/mes en Twilio). Fijo/local sale ~US$0,04/min.
- Traducción práctica: una llamada de 5 minutos ≈ **US$0,35**. Veinte urgencias al mes ≈ **US$7**. El costo no es un argumento en contra a este volumen.
- Ojo con los outliers: **Isla de Pascua, Punta Arenas y "servicios especiales" cuestan ~US$1,15/min** (25× más). Irrelevante si el destino es un móvil de Santiago, pero conviene tenerlo escrito.

**B — WhatsApp calling (Meta SIP, `wa.meta.vc`).** La llamada timbra dentro de WhatsApp, no en la red telefónica.

- **Chile sí está habilitado para llamadas iniciadas por el negocio.** Los países excluidos son los del número del negocio: EE.UU., Canadá, Egipto, Nigeria, Turquía y Vietnam. El número del *destinatario* puede ser de cualquier país.
- **Requiere permiso explícito del usuario**, obtenido de tres formas: un mensaje de solicitud de permiso que la persona acepta con un toque; implícito y **temporal** si la persona llama al negocio; o **permanente** si se opta desde el perfil del negocio.
- Límites de Meta: 1 solicitud cada 24 h, máximo 2 en 7 días. Concedido el permiso, ~5–10 llamadas conectadas por 24 h dentro de una ventana de 7 días; el permiso caduca a los 7 días y **se revoca solo tras 4 llamadas no contestadas**.
- Encaje técnico: Meta expone **SIP con autenticación digest** (`sip:+569...@wa.meta.vc;transport=tls`), media WebRTC (ICE, DTLS-SRTP, OPUS) y una contraseña SIP generada por Meta. Es decir: **es un troncal saliente más** para LiveKit, apuntando a `wa.meta.vc`.
- No se puede puentear una llamada de WhatsApp a PSTN. No nos afecta: nuestro extremo es un agente, no un teléfono.
- **A verificar antes de prometerlo:** el costo por minuto de Meta para llamadas. No lo tengo confirmado y no lo voy a inventar.

**Recomendación:** empezar por **A** para la fase 6 —timbra sin depender de permisos ni de que WhatsApp esté abierto, y a este volumen el costo es ruido—, y evaluar **B** después como optimización. Ambas detrás de `OUTBOUND_TRANSPORT=pstn|whatsapp|off`, con la misma interfaz: cambiar de transporte no debe tocar el agente.

### 6.2 El disparador: quién decide llamar

Atlas (Hermes) llama a `POST /calls/outbound` con un cuerpo explícito:

| campo | para qué |
|---|---|
| `to` | E.164, y **tiene que estar en la allowlist** (hoy: un solo número, el de Goli) |
| `severity` | `P0`/`P1` timbran · `P2` sólo mensaje en Discord |
| `reason` | una línea: qué pasó |
| `context` | lo que el agente necesita saber para explicarlo y responder preguntas |
| `dedupe_key` | idempotencia: la misma caída no llama dos veces (`prod:crm:down:2026-09-25`) |
| `expires_at` | una urgencia vieja no debe timbrar a las 3 de la mañana del día siguiente |

Respuesta: el `call_session_id` (el modelo ya existe) → **la llamada queda auditada** con su transcripción y su resumen, igual que cualquier otra.

### 6.3 Regla de oro: disparadores deterministas, no criterio del agente

**En la primera versión, Atlas no decide "esto es urgente" por su cuenta.** Las condiciones que timbran son observables y verificables:

- health check caído N chequeos consecutivos,
- un proceso PM2 muerto que debería estar vivo,
- disco sobre el umbral, o swap agotada,
- la instancia dejó de responder.

El juicio del agente ("me parece importante") **no** dispara una llamada. Suena restrictivo y es deliberado: un sistema que timbla a las 3 a.m. por un falso positivo pierde la confianza y queda apagado en una semana. Primero se gana el derecho a llamar; después, si hace falta, se amplía.

### 6.4 Independencia del sistema vigilado

**El que avisa no puede vivir dentro de lo que vigila.** Si el worker que hace la llamada corre en la misma instancia EC2 que el CRM, la caída de esa instancia se lleva puesto al que avisa. Por eso:

- el worker de llamadas salientes corre **fuera** de la instancia de producción (PC de Goli en el piloto; instancia propia después);
- y **Discord sigue siendo el canal de respaldo**: si la llamada falla, no conecta o no contesta, el aviso ya salió por texto. La llamada es una amplificación, nunca la única señal.

## 7. Guardarraíles de la llamada saliente

Llamar a un teléfono es **la capacidad más peligrosa de todo el ecosistema**. No por la llamada en sí, sino por lo que habilita si la allowlist se amplía sin cuidado. Va en un módulo propio (`app/services/outbound_policy.py`) y **cada control es una variable de entorno con el default más restrictivo**:

| control | default |
|---|---|
| `OUTBOUND_CALLS_ENABLED` | `false` — apagado; el endpoint responde 403 y no marca |
| Allowlist de destinos | sólo el número de Goli. Cualquier otro → `OUTBOUND_CALL_BLOCKED` |
| Máximo por día | 10, y nunca más de 1 en curso |
| Ventana de deduplicación | 6 h por `dedupe_key` |
| Horas de silencio | 23:00–07:00 sin llamada, **P0 incluido** salvo override explícito |
| Severidad mínima | `P1` (`P2` sólo texto) |
| Auditoría | cada decisión (timbró / no timbró y por qué) queda como evento en la sesión |

Esto **extiende** lo que ya existe: `compliance_service.py` ya valida E.164, consulta la lista de supresión y bloquea todo lo que no sea `ALLOWED_TEST_NUMBER`. La lista de supresión y el registro de eventos ya están en el esquema; no hay que inventar tablas.

**Y una línea que no se cruza en este piloto: no se llama a clientes.** Las llamadas salientes existen, en esta fase, sólo para Atlas → Goli. La atención saliente a clientes (campañas, seguimiento, cobranza) es fase 5 y necesita su propia decisión explícita, con consentimiento y normativa de por medio.

## 8. El cerebro: un solo lugar donde vive el contexto

El agente de voz **no** debería tener su propio cerebro. Si la conversación por voz no alcanza la knowledge base de Atlas ni el estado de los repos, terminamos con dos Atlas que saben cosas distintas — el mismo problema de "doble autoridad" que ya está identificado como `[P0]` entre el CRM y Customer Service.

**Propuesta (fase 4):** un adapter que exponga a Atlas como herramienta del agente. El LLM sigue siendo DeepSeek (que ya es el que Atlas usa); lo que cambia es que puede consultar. Se descarta de entrada duplicar la lógica de negocio dentro del servicio de voz.

Esto es lo que hace útil una llamada de urgencia: que del otro lado haya alguien que sabe qué estaba pasando en los repos, no un bot que sólo sabe repetir la alerta.

## 9. Higiene y operación

- **CI desde la fase 1.** Sin gate automático, "abro PRs para que los revises" no tiene red de seguridad.
- **Los tests existentes se conservan.** Los adaptadores nuevos se testean sin red (buffer sintético → texto esperado; texto → frames). **La capa de política se testea con tabla de casos**, que es donde de verdad importa: allowlist, cupos, horas, dedupe, kill switch.
- **Config por variables, con default = comportamiento actual.** Cada pieza nueva se puede apagar y volver al estado previo sin revertir código.
- **Logs estructurados** (ya se usan) y ninguna credencial en logs ni en `/diagnostics`. **Números de teléfono se enmascaran** en logs y en las respuestas de diagnóstico.
- **El demo del navegador es un cliente más**, no un camino paralelo.

## 10. Dónde corre

**El piloto, en el PC de Goli con `docker compose` local. No en la instancia EC2 de producción.**

Ver `atlas/infra-produccion.md` (verificación read-only del 2026-09-25): la instancia es una **t3.medium con 2 vCPU, 3.835 MB de RAM y cero swap**, ya sostiene nginx + MariaDB + 6 procesos PM2, tiene el disco al 76% y **hoy tiene 3 de 8 procesos caídos**. Instalar ahí un agente de voz en tiempo real —que necesita CPU continua y memoria— repetiría el incidente del 16-sep, esta vez por diseño.

**Pero la llamada de urgencia agrega un requisito nuevo: disponibilidad.** Un aviso que sólo funciona cuando el PC está encendido no sirve para vigilar producción. Dos consecuencias:

1. Mientras el piloto viva en el PC, **el PC es parte del camino crítico de alerta** y conviene tratarlo como tal (ya está configurado para no suspenderse).
2. Cuando la llamada de urgencia pase de experimento a real, **va a una instancia propia y chica, separada de producción**, y el disparador (el cron de Hermes o un chequeo externo) también vive fuera de la instancia vigilada. Es la §6.4 aplicada al despliegue.
