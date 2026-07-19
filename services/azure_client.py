import os
import time
import asyncio
import logging
from uuid import uuid4

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")

# Русский голос по умолчанию. Другие: ru-RU-SvetlanaNeural (жен.), ru-RU-DariyaNeural (жен.)
DEFAULT_VOICE = os.getenv("AZURE_TTS_VOICE", "ru-RU-DmitryNeural")

# Сколько раз пробовать при сетевом таймауте
TTS_MAX_RETRIES = 3


class VoiceServiceNotConfigured(Exception):
    pass


class VoiceServiceError(Exception):
    pass


def _speech_config() -> "speechsdk.SpeechConfig":
    key = os.getenv("AZURE_SPEECH_KEY", "")
    region = os.getenv("AZURE_SPEECH_REGION", "")
    if not key or not region:
        raise VoiceServiceNotConfigured(
            "AZURE_SPEECH_KEY / AZURE_SPEECH_REGION не настроены на сервере. "
            "Озвучка недоступна, пока администратор не подключит ключ Azure Speech."
        )
    cfg = speechsdk.SpeechConfig(subscription=key, region=region)
    # Выходной формат — MP3
    cfg.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3
    )
    # Увеличиваем таймауты, чтобы медленная/нестабильная сеть не обрывала синтез.
    cfg.set_property_by_name(
        "SpeechServiceConnection_SynthesisConnectionTimeoutMs", "30000"
    )
    cfg.set_property_by_name(
        "SpeechServiceConnection_InitialSilenceTimeoutMs", "10000"
    )
    return cfg


def _synthesize_once(text: str, voice: str) -> bytes:
    cfg = _speech_config()
    cfg.speech_synthesis_voice_name = voice
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)
    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return bytes(result.audio_data)

    if result.reason == speechsdk.ResultReason.Canceled:
        details = result.cancellation_details
        raise VoiceServiceError(
            f"Azure TTS отменён: {details.reason} — {details.error_details}"
        )
    raise VoiceServiceError(f"Azure TTS не удался: {result.reason}")


def _synthesize_blocking(text: str, voice: str) -> bytes:
    last_error = None
    for attempt in range(1, TTS_MAX_RETRIES + 1):
        try:
            return _synthesize_once(text, voice)
        except VoiceServiceError as exc:
            last_error = exc
            # Повторяем только сетевые таймауты — они обычно проходят со 2-3 раза
            if "Timeout" in str(exc) or "timeout" in str(exc):
                logger.warning("Azure TTS таймаут, попытка %s/%s, повтор…", attempt, TTS_MAX_RETRIES)
                time.sleep(1.5 * attempt)
                continue
            raise
    raise last_error


async def synthesize_speech(text: str, voice_id: str | None = None) -> tuple[bytes, str]:
    """
    Тот же интерфейс, что у elevenlabs_client.synthesize_speech.
    voice_id = имя голоса Azure (напр. 'ru-RU-DmitryNeural'); если None — берётся DEFAULT_VOICE.
    Возвращает (mp3_bytes, content_type).
    """
    voice = voice_id or DEFAULT_VOICE
    audio_bytes = await asyncio.to_thread(_synthesize_blocking, text, voice)
    return audio_bytes, "audio/mpeg"


def save_audio_file(audio_bytes: bytes, prefix: str = "narration") -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{prefix}_{uuid4().hex}.mp3"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(audio_bytes)
    return f"{APP_BASE_URL.rstrip('/')}/uploads/{filename}"


def is_configured() -> bool:
    return bool(os.getenv("AZURE_SPEECH_KEY") and os.getenv("AZURE_SPEECH_REGION"))


# Заглушка на случай вызова клонирования где-то ещё.
async def clone_voice_from_sample(*args, **kwargs) -> str:
    raise VoiceServiceNotConfigured(
        "Клонирование голоса недоступно на Azure Speech (нужен Custom Neural Voice). "
        "Используется стандартный русский голос."
    )