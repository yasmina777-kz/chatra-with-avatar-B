"""
Оркестрация полного пайплайна генерации лекции аватара, запускается
ПОСЛЕ одобрения админом (фоновой задачей FastAPI BackgroundTasks).

Шаги:
 1. Извлечь слайды из закреплённого файла (текст + картинки) — на этапе создания лекции уже сделано
 2. Сгенерировать текст рассказа для каждого слайда (OpenAI), под нужную длительность/стиль
 3. Озвучить каждый слайд клонированным голосом учителя (ElevenLabs)
 4. Сгенерировать короткое видео-интро аватара по первому аудио-фрагменту (D-ID), если настроен
 5. Если включено — сгенерировать итоговый конспект
 6. Обновить статус лекции на ready / failed
"""
import logging

from sqlalchemy.orm import Session

from db import get_session_for_org
from models import AvatarLecture, AvatarLectureSlide, TeacherAvatar
from services import elevenlabs_client, did_client, lecture_generator

logger = logging.getLogger(__name__)

INTRO_VIDEO_SLIDE_INDEX = 0  # видео-интро рендерится только для первого слайда


async def run_lecture_generation(lecture_id: int, org_type: str = "university") -> None:
    """
    Запускается в фоне (FastAPI BackgroundTasks) после одобрения лекции админом.
    Открывает свою собственную Session, так как Session из исходного HTTP-запроса
    к этому моменту уже закрыта.
    """
    db: Session = get_session_for_org(org_type)
    try:
        lecture = db.query(AvatarLecture).filter(AvatarLecture.id == lecture_id).first()
        if not lecture:
            logger.error("AvatarLecture %s не найдена для генерации", lecture_id)
            return

        lecture.status = "generating"
        db.commit()

        avatar = db.query(TeacherAvatar).filter(TeacherAvatar.id == lecture.avatar_id).first()
        slides = (
            db.query(AvatarLectureSlide)
            .filter(AvatarLectureSlide.lecture_id == lecture.id)
            .order_by(AvatarLectureSlide.slide_index)
            .all()
        )

        if not slides:
            lecture.status = "failed"
            lecture.error_message = "Не найдено слайдов для генерации"
            db.commit()
            return

        slide_texts = [s.slide_source_text or "" for s in slides]

        try:
            narrations = await lecture_generator.generate_lecture_narration(
                slide_texts=slide_texts,
                duration_minutes=lecture.duration_minutes,
                style=lecture.style,
                lecture_title=lecture.title,
            )
        except Exception as exc:
            logger.exception("Ошибка генерации текста лекции %s", lecture_id)
            lecture.status = "failed"
            lecture.error_message = f"Ошибка генерации текста: {exc}"
            db.commit()
            return

        for slide, narration in zip(slides, narrations):
            slide.narration_text = narration

        first_audio_url = None
        for i, slide in enumerate(slides):
            text = (slide.narration_text or "").strip()
            if not text:
                continue
            try:
                audio_bytes, _ctype = await elevenlabs_client.synthesize_speech(
                    text=text,
                    voice_id=avatar.elevenlabs_voice_id if avatar else None,
                )
                audio_url = elevenlabs_client.save_audio_file(audio_bytes, prefix=f"lecture{lecture.id}_slide{i}")
                slide.audio_url = audio_url
                if i == INTRO_VIDEO_SLIDE_INDEX:
                    first_audio_url = audio_url
            except elevenlabs_client.VoiceServiceNotConfigured as exc:
                logger.warning("ElevenLabs не настроен, слайд %s остаётся без аудио: %s", i, exc)
            except Exception as exc:
                logger.exception("Ошибка озвучки слайда %s лекции %s", i, lecture_id)
                slide.audio_url = None

        db.commit()

        # Видео-интро только для первого слайда, чтобы не сжигать бюджет D-ID
        if avatar and avatar.photo_url and first_audio_url:
            try:
                video_url = await did_client.create_talking_intro(
                    photo_url=avatar.photo_url,
                    audio_url=first_audio_url,
                )
                lecture.intro_video_url = video_url
            except did_client.VideoServiceNotConfigured as exc:
                logger.info("D-ID не настроен, видео-интро пропущено: %s", exc)
            except Exception:
                logger.exception("Ошибка генерации видео-интро лекции %s", lecture_id)

        if lecture.auto_summary:
            try:
                summary = await lecture_generator.generate_lecture_summary(
                    narrations=[s.narration_text or "" for s in slides],
                    lecture_title=lecture.title,
                    style=lecture.style,
                )
                lecture.summary_text = summary
            except Exception:
                logger.exception("Ошибка генерации конспекта лекции %s", lecture_id)

        lecture.status = "ready"
        db.commit()

    except Exception:
        logger.exception("Непредвиденная ошибка генерации лекции %s", lecture_id)
        try:
            lecture = db.query(AvatarLecture).filter(AvatarLecture.id == lecture_id).first()
            if lecture:
                lecture.status = "failed"
                lecture.error_message = "Внутренняя ошибка генерации"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
