# Piloto de voz — Arquitectura

> Autor: **Atlas** (agente) · Fecha: **2026-09-25** · Estado: **propuesta para revisión**
> Ver `ROADMAP.md` para la secuencia de PRs. Ver `docs/adr/0001-pipeline-unico-local-first.md` para la decisión principal.

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

**Consecuencia:** hoy `call-service` no puede sostener una conversación por ninguna de sus dos puertas.

## 2. Arquitectura objetivo

Una sola ruta de audio, con las piezas intercambiables por configuración.

```
Transporte            Orquestación              Cerebro            Habla
──────────            ────────────              ───────            ─────
LiveKit room   ──►    AgentSession    ──►    LLM (DeepSeek)  ──►  TTS
(Navegador /          + VAD silero          + bridge a Atlas      STT
 WhatsApp / SIP)      + turnos                                    (vía StreamAdapter)
```

Los cuatro eslabones quedan detrás de una variable de entorno. Nada de lo que sigue obliga a reescribir el pipeline cuando se cambie una pieza:

| pieza | opciones | default propuesto |
|---|---|---|
| Transporte | LiveKit (browser / WhatsApp / SIP) | **LiveKit** — el WhatsApp ya está construido encima |
| STT | `local` (faster-whisper) · `openai` · `groq` | **`local`** |
| TTS | `local` (edge-tts) · `openai` | **`local`** |
| LLM | DeepSeek (ya integrado) · otro OpenAI-compatible | **DeepSeek** (sin cambios) |
| Cerebro | chat aislado · **bridge a Atlas** | chat aislado ahora, bridge en fase 4 |

## 3. La decisión técnica de fondo: STT/TTS locales

### Por qué

1. **Desbloquea el repo sin gastar**: `OPENAI_API_KEY` está vacía y el pipeline no arranca. Con STT/TTS locales, corre sin ninguna credencial de voz.
2. **Costo marginal cero**: para un canal de voz con clientes, el STT/TTS cloud se paga por minuto y escala con el uso. `faster-whisper` local y `edge-tts` no.
3. **Es un camino soportado, no un hack.** La documentación de LiveKit (`docs.livekit.io/agents/models/stt/`) trata explícitamente el caso: Whisper no es streaming, así que se envuelve con `StreamAdapter` + VAD para que el VAD decida dónde termina el habla. Existe el mismo patrón para TTS (`livekit/agents/tts/stream_adapter.py`).
4. **Independencia de proveedor.** El mismo diseño acepta después un STT cloud rápido sin tocar la orquestación.

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

**Conclusión:** el piloto arranca con `base` y un benchmark que mida el turno completo de punta a punta. Si la latencia no alcanza, las salidas son (a) un VAD con ventana de silencio más corta, (b) un STT cloud rápido sólo para producción, o (c) GPU — y ninguna de las tres obliga a rediseñar: la capa ya quedó intercambiable por configuración.

## 5. El cerebro: un solo lugar donde vive el contexto

El agente de voz **no** debería tener su propio cerebro. Si la conversación por voz no alcanza la knowledge base de Atlas ni el estado de los repos, terminamos con dos Atlas que saben cosas distintas — el mismo problema de "doble autoridad" que ya está identificado como `[P0]` entre el CRM y Customer Service.

**Propuesta (fase 4):** un adapter que exponga a Atlas como herramienta del agente. El LLM sigue siendo DeepSeek (que ya es el que Atlas usa); lo que cambia es que puede consultar. Se descarta de entrada duplicar la lógica de negocio dentro del servicio de voz.

## 6. Higiene y operación

- **CI desde la fase 1.** Sin gate automático, "abro PRs para que los revises" no tiene red de seguridad.
- **Los tests existentes se conservan.** Los adaptadores nuevos se testean sin red (buffer sintético → texto esperado; texto → frames).
- **Config por variables, con default = comportamiento actual.** Cada pieza nueva se puede apagar y volver al estado previo sin revertir código.
- **Logs estructurados** (ya se usan) y ninguna credencial en logs ni en `/diagnostics`.
- **El demo del navegador es un cliente más**, no un camino paralelo.
