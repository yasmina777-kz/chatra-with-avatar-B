import logging

from sqlalchemy.orm import Session

from db import get_session_for_org
from models import AvatarLecture, AvatarLectureSlide, TeacherAvatar
from services import azure_client as tts_client, wav2lip_client, lecture_generator

logger = logging.getLogger(__name__)

INTRO_VIDEO_SLIDE_INDEX = 0


async def run_lecture_generation(lecture_id: int, org_type: str = "university") -> None:

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

        # Голос Azure: имя голоса хранится в поле avatar.elevenlabs_voice_id
        voice_name = avatar.elevenlabs_voice_id if avatar else None

        last_index = len(slides) - 1
        first_audio_url = None
        last_audio_url = None

        for i, slide in enumerate(slides):
            text = (slide.narration_text or "").strip()
            if not text:
                continue
            try:
                audio_bytes, _ctype = await tts_client.synthesize_speech(
                    text=text,
                    voice_id=voice_name,
                )
                audio_url = tts_client.save_audio_file(audio_bytes, prefix=f"lecture{lecture.id}_slide{i}")
                slide.audio_url = audio_url
                if i == INTRO_VIDEO_SLIDE_INDEX:
                    first_audio_url = audio_url
                if i == last_index:
                    last_audio_url = audio_url
            except tts_client.VoiceServiceNotConfigured as exc:
                logger.warning("Azure TTS не настроен, слайд %s остаётся без аудио: %s", i, exc)
            except Exception:
                logger.exception("Ошибка озвучки слайда %s лекции %s", i, lecture_id)
                slide.audio_url = None

        db.commit()

        # avatar.photo_url теперь может содержать ВИДЕО преподавателя (Wav2Lip принимает и видео, и фото).

        # 1) Говорящее видео-вступление (первый слайд)
        if avatar and avatar.photo_url and first_audio_url:
            try:
                intro_url = await wav2lip_client.generate_talking_video(
                    face=avatar.photo_url,
                    audio=first_audio_url,
                )
                lecture.intro_video_url = intro_url
            except wav2lip_client.Wav2LipError as exc:
                logger.info("Wav2Lip недоступен, видео-интро пропущено: %s", exc)
            except Exception:
                logger.exception("Ошибка генерации видео-интро лекции %s", lecture_id)

        # 2) Говорящее видео-концовка (последний слайд) — только если он не совпадает со вступлением
        if (
            avatar
            and avatar.photo_url
            and last_audio_url
            and last_audio_url != first_audio_url
        ):
            try:
                outro_url = await wav2lip_client.generate_talking_video(
                    face=avatar.photo_url,
                    audio=last_audio_url,
                )
                lecture.outro_video_url = outro_url
            except wav2lip_client.Wav2LipError as exc:
                logger.info("Wav2Lip недоступен, видео-концовка пропущена: %s", exc)
            except Exception:
                logger.exception("Ошибка генерации видео-концовки лекции %s", lecture_id)

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