import json
import logging
import os
import re
import httpx

logger = logging.getLogger(__name__)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4o-mini"


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


async def _chat(
    messages: list[dict],
    max_tokens: int = 4000,
    temperature: float = 0.6,
    json_mode: bool = False,
) -> str:
    api_key = _api_key()
    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        # Принуждаем модель вернуть валидный JSON-объект
        payload["response_format"] = {"type": "json_object"}

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
        "5. Не используй обратные слэши, пути к файлам и спецсимволы — текст читается вслух, "
        "поэтому пиши словами (например, вместо «\\n» скажи «новая строка»).\n"
        "6. Ответь СТРОГО в виде JSON-объекта вида: "
        '{"narrations": ["текст рассказа слайда 1", "текст рассказа слайда 2", ...]}\n'
        f"Массив narrations должен содержать ровно {len(slide_texts)} элементов."
    )

    content = await _chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": slides_block},
        ],
        max_tokens=min(4096, 300 + len(slide_texts) * 220),
        json_mode=True,
    )

    narrations = _parse_json_array(content, expected_len=len(slide_texts))
    return narrations


async def generate_lecture_summary(narrations: list[str], lecture_title: str, style: str) -> str:

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


def _fix_bad_escapes(s: str) -> str:
    """Экранирует одиночные обратные слэши, которые не являются валидной JSON-escape."""
    return re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', s)


def _parse_json_array(content: str, expected_len: int) -> list[str]:
    text = content.strip()

    # снимаем markdown-обёртку ```json ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    def _try(s: str):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    parsed = _try(text)

    # попытка 2: чиним невалидные escape-последовательности (пути вида C:\Users, \n и т.п.)
    if parsed is None:
        parsed = _try(_fix_bad_escapes(text))

    # попытка 3: вырезаем объект {...} или массив [...] по скобкам
    if parsed is None:
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start, end = text.find(open_ch), text.rfind(close_ch)
            if start != -1 and end != -1 and end > start:
                candidate = text[start:end + 1]
                parsed = _try(candidate) or _try(_fix_bad_escapes(candidate))
                if parsed is not None:
                    break

    if parsed is None:
        logger.error("Не удалось распарсить JSON ответа модели. Ответ: %s", text[:500])
        raise LectureGenerationError("ИИ вернул некорректный формат ответа, попробуйте снова")

    # поддерживаем и {"narrations": [...]}, и просто [...]
    if isinstance(parsed, dict):
        for key in ("narrations", "slides", "texts", "result", "data"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            # если в объекте одно единственное поле-список — берём его
            lists = [v for v in parsed.values() if isinstance(v, list)]
            if len(lists) == 1:
                parsed = lists[0]

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

    voice_cost = (total_chars / 1000) * 0.30
    video_cost = (intro_video_seconds / 60) * 4.0
    return round(voice_cost + video_cost, 2)