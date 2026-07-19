import os
import time
import asyncio
import logging
import tempfile
from uuid import uuid4
from urllib.parse import urlparse

import httpx
import replicate

logger = logging.getLogger(__name__)

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")

# Модель на Replicate. SadTalker: фото/видео + аудио -> говорящее видео.
# Если Replicate вернёт "version not found" — зайди на https://replicate.com/cjwbw/sadtalker,
# скопируй актуальный version-хеш и подставь в REPLICATE_LIPSYNC_MODEL в .env.
REPLICATE_LIPSYNC_MODEL = os.getenv(
    "REPLICATE_LIPSYNC_MODEL",
    "cjwbw/sadtalker:3aa3dac9353cc4d6bd62a8f95957bd844003b401ca4e4a9b33baa574c549d376",
)

# Сколько раз повторять при сетевых таймаутах (медленный интернет)
MAX_RETRIES = 3
# Таймауты на запросы к Replicate: connect / read / write / pool
HTTP_TIMEOUT = httpx.Timeout(connect=60.0, read=600.0, write=600.0, pool=60.0)


class Wav2LipError(Exception):
    pass


def is_available() -> bool:
    return bool(os.getenv("REPLICATE_API_TOKEN"))


def _client() -> "replicate.Client":
    """Клиент Replicate с увеличенными таймаутами (для медленной сети)."""
    return replicate.Client(
        api_token=os.getenv("REPLICATE_API_TOKEN"),
        timeout=HTTP_TIMEOUT,
    )


def _resolve_to_local_path(src: str, tmpdir: str) -> str:
    if os.path.exists(src):
        return src

    parsed = urlparse(src)
    if parsed.path:
        name = os.path.basename(parsed.path)
        candidate = os.path.join(UPLOAD_DIR, name)
        if os.path.exists(candidate):
            return candidate

    if src.startswith("http"):
        ext = os.path.splitext(parsed.path)[1] or ".bin"
        dst = os.path.join(tmpdir, f"in_{uuid4().hex}{ext}")
        with httpx.Client(timeout=300) as client:
            with client.stream("GET", src) as r:
                r.raise_for_status()
                with open(dst, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
        return dst

    raise Wav2LipError(f"Не удалось найти файл: {src}")


def _run_once(face: str, audio: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        face_path = _resolve_to_local_path(face, tmpdir)
        audio_path = _resolve_to_local_path(audio, tmpdir)
        with open(face_path, "rb") as face_f, open(audio_path, "rb") as audio_f:
            output = _client().run(
                REPLICATE_LIPSYNC_MODEL,
                input={
                    "source_image": face_f,
                    "driven_audio": audio_f,
                    "preprocess": "crop",
                    "still": True,
                },
            )
    return str(output)


def _run_blocking(face: str, audio: str) -> str:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return _run_once(face, audio)
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout,
                httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            last_error = exc
            logger.warning(
                "Сетевой таймаут при обращении к Replicate, попытка %s/%s: %s",
                attempt, MAX_RETRIES, exc,
            )
            time.sleep(3 * attempt)
            continue
    raise Wav2LipError(
        f"Не удалось связаться с Replicate после {MAX_RETRIES} попыток "
        f"(медленное или нестабильное соединение): {last_error}"
    )


async def generate_talking_video(face: str, audio: str) -> str:
    """
    Оживление фото/видео через Replicate (SadTalker).
    Принимает лицо (ФОТО или видео) + аудио, возвращает публичный URL к mp4.
    face/audio могут быть локальным путём ИЛИ URL.
    """
    if not is_available():
        raise Wav2LipError("REPLICATE_API_TOKEN не настроен в .env")

    logger.info("SadTalker (Replicate) старт: face=%s", face)
    result_url = await asyncio.to_thread(_run_blocking, face, audio)

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    out_name = f"talk_{uuid4().hex[:12]}.mp4"
    out_path = os.path.join(UPLOAD_DIR, out_name)
    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.get(result_url)
        resp.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(resp.content)

    logger.info("SadTalker (Replicate) готово: %s", out_path)
    return f"{APP_BASE_URL.rstrip('/')}/uploads/{out_name}"