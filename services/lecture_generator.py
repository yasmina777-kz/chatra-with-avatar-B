"""
Генерация текста лекции аватара по слайдам презентации/документа.

Учитель указывает:
  - желаемую длительность лекции (в минутах) — выбирается самим учителем
  - стиль объяснения: school | university | professional
  - нужен ли автоматический итоговый конспект

ИИ распределяет общее время речи по слайдам пропорционально объёму
содержания каждого слайда и пишет связный текст рассказа для каждого слайда,
а также (если запрошено) финальный конспект по всей лекции.
"""
import json
import logging
import os
import httpx

logger = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"

# Среднее количество слов в минуту при спокойной речи преподавателя
WORDS_PER_MINUTE = 130

STYLE_PROMPTS = {
    "school": (
        "Объясняй очень просто, как школьному учителю для подростков: простые слова, "
        "конкретные примеры из жизни, без сложных терминов без объяснения, дружелюбный тон."
    ),
    "university": (
        "Объясняй как университетский преподаватель: используй академическую терминологию, "
        "но поясняй её, давай логичную структуру рассуждения, можно ссылаться на смежные темы."
    ),
    "professional": (
        "Объясняй как эксперт-практик для профессиональной аудитории: глубоко, по существу, "
        "с акцентом на практическое применение, без лишних разжёвываний базовых вещей."
    ),
}


class LectureGenerationError(Exception):
    pass


def _api_key() -> str:
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        raise LectureGenerationError("OPENAI_API_KEY не настроен на сервере")
    return key


async def _chat(messages: list[dict], max_tokens: int = 4000, temperature: float = 0.6) -> str:
    api_key = _api_key()
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            OPENAI_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    if not resp.is_success:
        try:
            err = resp.json().get("error", {}).get("message", "OpenAI error")
        except Exception:
            err = f"OpenAI error {resp.status_code}"
        raise LectureGenerationError(err)

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _distribute_seconds(slide_texts: list[str], total_seconds: int) -> list[int]:
    """Делит общее время лекции по слайдам пропорционально объёму текста на слайде."""
    weights = [max(len(t), 30) for t in slide_texts]
    total_weight = sum(weights) or 1
    seconds = [max(int(total_seconds * w / total_weight), 15) for w in weights]
    return seconds


async def generate_lecture_narration(
    slide_texts: list[str],
    duration_minutes: int,
    style: str,
    lecture_title: str,
) -> list[str]:
    """
    Возвращает список текстов рассказа — один на каждый слайд,
    суммарно рассчитанный на duration_minutes речи.
    """
    style_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["university"])
    total_words = duration_minutes * WORDS_PER_MINUTE
    seconds_per_slide = _distribute_seconds(slide_texts, duration_minutes * 60)

    slides_block = "\n\n".join(
        f"### Слайд {i + 1} (целевая длительность рассказа ~{seconds_per_slide[i]} сек, "
        f"~{int(seconds_per_slide[i] / 60 * WORDS_PER_MINUTE)} слов)\n"
        f"Содержимое слайда:\n{text[:3000]}"
        for i, text in enumerate(slide_texts)
    )

    system_prompt = (
        "Ты — преподаватель, озвучивающий лекцию по презентации в виде аватара. "
        "Для каждого слайда напиши связный устный рассказ (то, что ты произнесёшь вслух), "
        "который раскрывает содержимое слайда. " + style_instruction + "\n\n"
        f"Тема лекции: «{lecture_title}». Общая длительность лекции — примерно {duration_minutes} минут "
        f"(~{total_words} слов суммарно по всем слайдам).\n\n"
        "ВАЖНЫЕ ПРАВИЛА:\n"
        "1. Пиши ТОЛЬКО то, что будет произнесено голосом — без заголовков, маркеров списков, markdown.\n"
        "2. Не повторяй текст слайда буквально — объясняй его своими словами, как живой рассказ.\n"
        "3. Соблюдай целевую длительность для каждого слайда (она указана в словах).\n"
        "4. Между слайдами должна быть логическая связность (используй переходные фразы типа "
        "«теперь перейдём к...», «как мы только что разобрали...»).\n"
        "5. Ответь СТРОГО в формате JSON-массива строк, без пояснений: "
        '["текст рассказа слайда 1", "текст рассказа слайда 2", ...]\n'
        f"Массив должен содержать ровно {len(slide_texts)} элементов."
    )

    content = await _chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": slides_block},
        ],
        max_tokens=min(4096, 300 + len(slide_texts) * 220),
    )

    narrations = _parse_json_array(content, expected_len=len(slide_texts))
    return narrations


async def generate_lecture_summary(narrations: list[str], lecture_title: str, style: str) -> str:
    """Финальный конспект по теме лекции — для студентов, в конце урока."""
    style_instruction = STYLE_PROMPTS.get(style, STYLE_PROMPTS["university"])
    full_text = "\n\n".join(narrations)

    system_prompt = (
        "Ты — преподаватель. По тексту прочитанной лекции составь краткий, но содержательный "
        "конспект для студентов: ключевые определения, формулы/факты, основные выводы. "
        + style_instruction + "\n\n"
        "Формат: Markdown с заголовками и списками. Конспект должен помещаться на 1-2 экрана — "
        "не пересказывай лекцию целиком, выдели только главное."
    )

    content = await _chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Тема: {lecture_title}\n\nТекст лекции:\n{full_text[:14000]}"},
        ],
        max_tokens=1200,
        temperature=0.4,
    )
    return content.strip()


def _parse_json_array(content: str, expected_len: int) -> list[str]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Не удалось распарсить JSON ответа модели: %s\nОтвет: %s", exc, text[:500])
        raise LectureGenerationError("ИИ вернул некорректный формат ответа, попробуйте снова")

    if not isinstance(parsed, list):
        raise LectureGenerationError("ИИ вернул не массив текстов слайдов")

    parsed = [str(x) for x in parsed]

    if len(parsed) < expected_len:
        parsed += [""] * (expected_len - len(parsed))
    elif len(parsed) > expected_len:
        parsed = parsed[:expected_len]

    return parsed


def estimate_total_chars(narrations: list[str]) -> int:
    return sum(len(t) for t in narrations)


def estimate_cost_usd(total_chars: int, intro_video_seconds: int = 20) -> float:
    """
    Грубая прикидка стоимости для отображения админу при модерации.
    ElevenLabs overage ~ $0.30 / 1000 символов (тариф Creator) как верхняя оценка.
    D-ID: видео только интро, ~$4/мин сверх лимита плана (ориентировочно).
    """
    voice_cost = (total_chars / 1000) * 0.30
    video_cost = (intro_video_seconds / 60) * 4.0
    return round(voice_cost + video_cost, 2)
