import asyncio
import json as _json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from db import SessionLocal
from crud import assignments as crud
from services.ai_grader import grade_submission as _ai_grade, _fetch_file_text

logger = logging.getLogger("deadline_checker")

async def _grade_one(db: Session, submission, assignment) -> None:
    sub_id = submission.id
    try:
        criteria = _json.loads(assignment.criteria) if assignment.criteria else []
        if not criteria:
            logger.warning("Задание %s: нет критериев, пропускаем сдачу %s", assignment.id, sub_id)
            return

        crud.set_submission_status(db, sub_id, "grading")

        full_text = submission.text_content or ""
        all_urls: list = []
        if submission.file_urls:
            try:
                all_urls = _json.loads(submission.file_urls)
            except Exception:
                pass
        if not all_urls and submission.file_url:
            all_urls = [submission.file_url]

        for i, url in enumerate(all_urls):
            file_text = await _fetch_file_text(url)
            if file_text.strip():
                label = f"ФАЙЛ {i+1}" if len(all_urls) > 1 else "СОДЕРЖИМОЕ ФАЙЛА"
                full_text = (
                    (full_text + f"\n\n{label}:\n" + file_text).strip()
                    if full_text
                    else f"{label}:\n{file_text}"
                )

        if not full_text:
            full_text = f"[Студент сдал файл(ы), но прочитать не удалось: {', '.join(all_urls)}]"

        result = await _ai_grade(
            text=full_text,
            file_url=None,
            criteria=criteria,
            max_score=assignment.max_score,
            reference_solution_url=assignment.reference_solution_url or None,
        )

        crud.set_submission_status(db, sub_id, "graded")
        crud.create_or_update_grade(
            db=db,
            submission_id=sub_id,
            score=result["score"],
            feedback=result.get("feedback"),
            criteria_scores=result.get("criteria_scores"),
            graded_by="ai",
        )
        logger.info("Сдача %s оценена ИИ: %s/%s", sub_id, result["score"], assignment.max_score)

    except Exception as e:
        logger.error("Ошибка при оценке сдачи %s: %s", sub_id, e)
        try:
            crud.set_submission_status(db, sub_id, "submitted")
        except Exception:
            pass

async def _check_deadlines() -> None:
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        all_assignments = crud.get_all_assignments(db)
        expired = [
            a for a in all_assignments
            if a.deadline and a.deadline <= now and a.is_active
        ]

        for assignment in expired:
            submissions = crud.get_submissions_for_assignment(db, assignment.id)
            ungraded = [
                s for s in submissions
                if s.status in ("submitted", "late") and not s.grade
            ]

            if not ungraded:
                continue

            logger.info(
                "Дедлайн задания '%s' (#%s) истёк. Запуск ИИ-оценки для %s сдач.",
                assignment.title, assignment.id, len(ungraded),
            )

            for submission in ungraded:
                await _grade_one(db, submission, assignment)
                await asyncio.sleep(1)

    except Exception as e:
        logger.error("Ошибка в deadline_checker: %s", e)
    finally:
        db.close()

async def deadline_checker_loop() -> None:
    logger.info("Deadline checker запущен (интервал: 60 сек)")
    while True:
        await _check_deadlines()
        await asyncio.sleep(60)
