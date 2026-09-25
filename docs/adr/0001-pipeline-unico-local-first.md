# ADR 0001 — Un solo pipeline de voz, local-first

- **Estado:** propuesto (pendiente de aprobación de Joaquín)
- **Fecha:** 2026-09-25
- **Autor:** Atlas (agente)
- **Repo:** `MS-pesaschile-call-service`

## Contexto

El servicio tiene **dos caminos de voz independientes** y **ninguno ejecutable**:

1. **LiveKit** (`app/core/livekit_agent_worker.py`): room + `AgentSession` con LLM DeepSeek, STT y TTS de OpenAI.
2. **OpenAI Realtime** (`app/core/agent.py`, `app/api/demo.py`): el navegador negocia SDP contra la API de Realtime, con el servidor proxiando una clave efímera.

Ambos dependen de `OPENAI_API_KEY`, que está **vacía**. Los dos caminos levantan `AppError` 503: verificado en `build_stt()`, `build_tts()` y `ensure_configured()`. El provider `local_webrtc` declara un transporte que no implementa (guarda estados en un `dict`; la media la maneja el navegador contra OpenAI).

Además, el objetivo declarado es usar este servicio para hablar por voz primero entre nosotros y después con clientes. Un canal de voz con clientes paga STT/TTS **por minuto**, y esa factura escala con el uso; y la instancia de producción disponible (t3.medium, 3,8 GB, sin swap, ya con 3 de 8 procesos caídos) no tiene margen para un agente de voz en tiempo real.

## Decisión

**Un solo pipeline —LiveKit— con las piezas de habla detrás de configuración, y STT/TTS locales por default.**

- El transporte es LiveKit para todos los casos (navegador ahora; WhatsApp y SIP después, que ya están construidos encima).
- `STT_PROVIDER` y `TTS_PROVIDER` (`local` | `openai` | futuro `groq`) seleccionan el motor. **El default es `local`.**
- STT: `faster-whisper` envuelto en `stt.StreamAdapter` + VAD (Whisper no es streaming; es el patrón que documenta LiveKit para este caso exacto).
- TTS: `edge-tts` envuelto en el `StreamAdapter` de TTS de LiveKit.
- Se retira el camino de OpenAI Realtime del demo del navegador, o queda detrás de un flag explícito y documentado como alternativa.

## Alternativas consideradas

| # | alternativa | por qué no |
|---|---|---|
| 1 | Mantener los dos caminos y elegir a mano | Sigue habiendo dos lugares donde arreglar cada cosa, y ninguno es el camino que usarán los clientes. Ya generó el malentendido de `local_webrtc`. |
| 2 | Unificar en OpenAI Realtime (el camino del navegador) | El flujo de WhatsApp y el futuro SIP son LiveKit. Realtime no hace telefonía. Y cuesta por minuto. |
| 3 | STT/TTS cloud baratos (Groq, Deepgram) por default | Buena latencia, pero sigue siendo dependencia externa y costo variable por minuto para un piloto que no lo necesita. **Se mantiene como opción de configuración**, no como default. |
| 4 | Escribir todo de cero sin LiveKit Agents | Descartar el SDK significa reimplementar VAD, turnos, interrupciones y transporte. El valor del piloto no está ahí. |
| 5 | Instalar un plugin de terceros y no escribir nada | Acopla el roadmap al mantenimiento de otro. Se evalúa primero como spike de 1 hora; si resulta sólido, se usa y se documenta la dependencia. |

## Consecuencias

**A favor**
- El pipeline arranca sin `OPENAI_API_KEY`: hoy es un repositorio que no puede hablar.
- Costo marginal de voz ≈ 0 en el piloto, y el costo por minuto deja de ser una variable crítica al pasar a clientes.
- Cada pieza es reemplazable por variable de entorno: probar un STT cloud no toca la orquestación.
- Un solo lugar donde vive el audio, y el demo del navegador pasa a ser un cliente más.

**En contra / riesgos**
- **Latencia**: en CPU y con modelo `base` el turno queda en ≈ 2–2,5 s (medido). Si el objetivo es conversación fluida, esto está en el límite. Mitigaciones en `ARQUITECTURA.md` §4; ninguna exige rediseño.
- **`edge-tts` requiere red** (Microsoft). Para un servicio que deba ser autónomo, `Piper` es el candidato; se decide en la fase 5.
- **Escribir dos adaptadores es trabajo real**: hay que cumplir el contrato exacto de `livekit-agents==1.5.12`, no el de la documentación web. Se valida contra el paquete instalado.
- Retirar el camino de Realtime es **código que se borra**: si alguien lo estaba usando, se rompe. Por eso la fase 3 lo deja detrás de un flag antes de eliminarlo.

## Verificación pendiente antes de implementar

1. Firma exacta de `stt.STT._recognize_impl` y de `tts.TTS.synthesize` en `livekit-agents==1.5.12`.
2. Que el `docker-compose` local levante el worker LiveKit contra el LiveKit configurado, sin gastar en APIs de voz.
3. Latencia de turno completo medida de punta a punta, no por partes.
