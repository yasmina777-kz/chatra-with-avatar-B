"""
Клиент D-ID: генерация короткого говорящего видео-интро аватара
(фото учителя + аудио -> видео с движением губ/лица).

Используется ТОЛЬКО для короткого вступления лекции (15-30 секунд) —
полное видео на всю лекцию обходится слишком дорого по тарифам D-ID.
Основная часть лекции показывается как статичное фото + слайд + аудио.

Ключ берётся из переменной окружения DID_API_KEY.
"""
import asyncio
import logging
import os
from uuid import uuid4

import httpx

logger = logging.getLogger(__name__)

DID_BASE_URL = "https://api.d-id.com"
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")

_POLL_INTERVAL_SECONDS = 3
_MAX_POLL_ATTEMPTS = 60


class VideoServiceNotConfigured(Exception):
    pass


class VideoServiceError(Exception):
    pass


def _auth_header() -> dict:
    key = os.getenv("DID_API_KEY", "")
    if not key:
        raise VideoServiceNotConfigured(
            "DID_API_KEY не настроен на сервере. Видео-интро аватара недоступно, "
            "пока администратор не подключит ключ D-ID."
        )
    return {"Authorization": f"Basic {key}" if ":" in key else f"Bearer {key}"}


async def create_talking_intro(photo_url: str, audio_url: str) -> str:
    headers = {**_auth_header(), "Content-Type": "application/json"}

    payload = {
        "source_url": photo_url,
        "script": {
            "type": "audio",
            "audio_url": audio_url,
        },
        "config": {"fluent": True, "pad_audio": 0.0},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        create_resp = await client.post(f"{DID_BASE_URL}/talks", headers=headers, json=payload)

    if not create_resp.is_success:
        logger.error("D-ID create talk failed: %s %s", create_resp.status_code, create_resp.text[:500])
        raise VideoServiceError(f"Не удалось создать видео-интро (D-ID error {create_resp.status_code})")

    talk_id = create_resp.json().get("id")
    if not talk_id:
        raise VideoServiceError("D-ID не вернул id задачи")

    result_url = await _poll_for_result(talk_id, headers)
    return await _download_and_save(result_url)


async def _poll_for_result(talk_id: str, headers: dict) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(_MAX_POLL_ATTEMPTS):
            resp = await client.get(f"{DID_BASE_URL}/talks/{talk_id}", headers=headers)
            if resp.is_success:
                data = resp.json()
                status = data.get("status")
                if status == "done":
                    result_url = data.get("result_url")
                    if result_url:
                        return result_url
                elif status == "error":
                    raise VideoServiceError(f"D-ID вернул ошибку рендера: {data.get('error')}")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    raise VideoServiceError("Превышено время ожидания рендера видео D-ID")


async def _download_and_save(video_url: str) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(video_url)
    if not resp.is_success:
        raise VideoServiceError("Не удалось скачать готовое видео с D-ID")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"intro_{uuid4().hex}.mp4"
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "wb") as f:
        f.write(resp.content)

    return f"{APP_BASE_URL.rstrip('/')}/uploads/{filename}"


def is_configured() -> bool:
    return bool(os.getenv("DID_API_KEY"))
