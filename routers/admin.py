import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import json
from datetime import datetime
from models import User, AiUsageLog, Posts, post_enrollments, TeacherAvatar, AvatarLecture
import schemas
from schemas import UserCreate, UserResponse
from deps import get_current_admin, get_current_user
from db import get_db
from crud import users as crud_users
from security import hash_password
from typing import Optional, List
from services import elevenlabs_client
from services.avatar_lecture_pipeline import run_lecture_generation

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(get_current_admin)]
)

@router.post("/users", response_model=UserResponse)
def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    existing = crud_users.get_user_by_email(db, user.email, current_user.org_type)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    hashed_password = hash_password(user.password)

    db_user = User(
        email=user.email,
        hashed_password=hashed_password,
        role=user.role,
        org_type=current_user.org_type,
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user

@router.get("/users", response_model=list[UserResponse])
def get_users(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    return db.query(User).filter(User.org_type == current_user.org_type).all()

@router.put("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    new_role: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.org_type != current_user.org_type:
        raise HTTPException(status_code=403, detail="Нет доступа")

    user.role = new_role
    db.commit()

    return {"message": "Role updated"}

@router.put("/users/{user_id}/block")
def block_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.org_type != current_user.org_type:
        raise HTTPException(status_code=403, detail="Нет доступа")

    user.is_active = False
    db.commit()

    return {"message": "User blocked"}

@router.put("/users/{user_id}/unblock")
def unblock_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.org_type != current_user.org_type:
        raise HTTPException(status_code=403, detail="Нет доступа")

    user.is_active = True
    db.commit()

    return {"message": "User unblocked"}

@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.org_type != current_user.org_type:
        raise HTTPException(status_code=403, detail="Нет доступа")

    db.delete(user)
    db.commit()

    return {"message": "User deleted"}

@router.get("/classes/{post_id}/members", response_model=list[UserResponse])
def get_class_members(
    post_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    post = db.query(Posts).filter(Posts.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Not found")
    creator = db.query(User).filter(User.id == post.user_id).first()
    if not creator or creator.org_type != current_user.org_type:
        raise HTTPException(status_code=404, detail="Not found")
    return (
        db.query(User)
        .join(post_enrollments, User.id == post_enrollments.c.user_id)
        .filter(
            post_enrollments.c.post_id == post_id,
            User.org_type == current_user.org_type,
        )
        .all()
    )

@router.get("/ai-usage")
def get_ai_usage(
    class_id: Optional[int] = Query(None, description="Filter by class, None = all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    from sqlalchemy import desc, func
    q = db.query(AiUsageLog).filter(AiUsageLog.org_type == current_user.org_type)
    if class_id is not None:
        q = q.filter(AiUsageLog.class_id == class_id)
    total = q.count()
    logs = (
        q.order_by(desc(AiUsageLog.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": l.id,
                "user_id": l.user_id,
                "class_id": l.class_id,
                "endpoint": l.endpoint,
                "prompt_tokens": l.prompt_tokens,
                "completion_tokens": l.completion_tokens,
                "total_tokens": l.total_tokens,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }

@router.get("/ai-usage/summary")
def get_ai_usage_summary(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    from sqlalchemy import func
    rows = (
        db.query(
            AiUsageLog.class_id,
            func.sum(AiUsageLog.total_tokens).label("total_tokens"),
            func.sum(AiUsageLog.prompt_tokens).label("prompt_tokens"),
            func.sum(AiUsageLog.completion_tokens).label("completion_tokens"),
            func.count(AiUsageLog.id).label("request_count"),
        )
        .filter(AiUsageLog.org_type == current_user.org_type)
        .group_by(AiUsageLog.class_id)
        .all()
    )
    return [
        {
            "class_id": r.class_id,
            "total_tokens": r.total_tokens or 0,
            "prompt_tokens": r.prompt_tokens or 0,
            "completion_tokens": r.completion_tokens or 0,
            "request_count": r.request_count or 0,
        }
        for r in rows
    ]


# ──────────────────────────────────────────────────────────────────
#  Модерация AI-аватаров преподавателей и лекций
#  (создание аватара и каждой новой лекции — затратные операции,
#   поэтому требуют явного одобрения админа)
# ──────────────────────────────────────────────────────────────────

@router.get("/avatars", response_model=List[schemas.TeacherAvatarResponse])
def list_avatars(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    q = db.query(TeacherAvatar).filter(TeacherAvatar.org_type == current_user.org_type)
    if status_filter:
        q = q.filter(TeacherAvatar.status == status_filter)
    return q.order_by(TeacherAvatar.created_at.desc()).all()


@router.post("/avatars/{avatar_id}/review", response_model=schemas.TeacherAvatarResponse)
async def review_avatar(
    avatar_id: int,
    body: schemas.AvatarReviewAction,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    avatar = db.query(TeacherAvatar).filter(TeacherAvatar.id == avatar_id).first()
    if not avatar or avatar.org_type != current_user.org_type:
        raise HTTPException(status_code=404, detail="Заявка на аватар не найдена")
    if avatar.status != "pending":
        raise HTTPException(status_code=409, detail="Заявка уже рассмотрена")

    avatar.reviewed_by = current_user.id
    avatar.reviewed_at = datetime.utcnow()

    if not body.approve:
        avatar.status = "rejected"
        avatar.rejection_reason = body.rejection_reason or "Отклонено администратором"
        db.commit()
        db.refresh(avatar)
        return avatar

    # Одобрено -> пытаемся клонировать голос учителя по образцу.
    # Если клонирование недоступно (нет ключа, нет платного тарифа, ошибка сети) —
    # всё равно одобряем аватара, но он будет говорить стандартным голосом ElevenLabs,
    # пока администратор не подключит/не обновит тариф.
    voice_warning = None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as client:
            sample_resp = await client.get(avatar.voice_sample_url)
        if not sample_resp.is_success:
            voice_warning = "Не удалось скачать образец голоса для клонирования"
        else:
            voice_id = await elevenlabs_client.clone_voice_from_sample(
                voice_name=avatar.display_name or f"teacher_{avatar.teacher_id}",
                sample_bytes=sample_resp.content,
                sample_filename="sample.mp3",
            )
            avatar.elevenlabs_voice_id = voice_id
    except elevenlabs_client.VoiceServiceNotConfigured as exc:
        logger.warning("ElevenLabs не настроен при одобрении аватара %s: %s", avatar_id, exc)
        voice_warning = "Ключ ElevenLabs не настроен — аватар будет говорить стандартным голосом"
    except elevenlabs_client.VoiceServiceError as exc:
        logger.warning("Клонирование голоса недоступно для аватара %s: %s", avatar_id, exc)
        voice_warning = (
            "Клонирование голоса недоступно на текущем тарифе ElevenLabs "
            "(нужен платный план Starter и выше) — аватар будет говорить стандартным голосом"
        )
    except Exception as exc:
        logger.exception("Непредвиденная ошибка клонирования голоса для аватара %s", avatar_id)
        voice_warning = f"Не удалось клонировать голос ({exc}) — аватар будет говорить стандартным голосом"

    avatar.status = "approved"
    avatar.rejection_reason = None
    avatar.voice_clone_warning = voice_warning
    db.commit()
    db.refresh(avatar)
    return avatar


@router.delete("/avatars/{avatar_id}")
def delete_avatar(
    avatar_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    avatar = db.query(TeacherAvatar).filter(TeacherAvatar.id == avatar_id).first()
    if not avatar or avatar.org_type != current_user.org_type:
        raise HTTPException(status_code=404, detail="Аватар не найден")
    db.delete(avatar)
    db.commit()
    return {"message": "Аватар удалён"}


@router.get("/avatar-lectures", response_model=List[schemas.AvatarLectureResponse])
def list_avatar_lectures(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    q = db.query(AvatarLecture).filter(AvatarLecture.org_type == current_user.org_type)
    if status_filter:
        q = q.filter(AvatarLecture.status == status_filter)
    return q.order_by(AvatarLecture.created_at.desc()).all()


@router.post("/avatar-lectures/{lecture_id}/review", response_model=schemas.AvatarLectureResponse)
def review_avatar_lecture(
    lecture_id: int,
    body: schemas.LectureReviewAction,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_admin),
):
    lecture = db.query(AvatarLecture).filter(AvatarLecture.id == lecture_id).first()
    if not lecture or lecture.org_type != current_user.org_type:
        raise HTTPException(status_code=404, detail="Лекция не найдена")
    if lecture.status != "pending_approval":
        raise HTTPException(status_code=409, detail="Лекция уже рассмотрена")

    lecture.reviewed_by = current_user.id
    lecture.reviewed_at = datetime.utcnow()

    if not body.approve:
        lecture.status = "rejected"
        lecture.rejection_reason = body.rejection_reason or "Отклонено администратором"
        db.commit()
        db.refresh(lecture)
        return lecture

    lecture.status = "approved"
    lecture.rejection_reason = None
    db.commit()
    db.refresh(lecture)

    # Генерация текста/аудио/видео — долгая, запускаем в фоне, чтобы не держать запрос админа
    background_tasks.add_task(run_lecture_generation, lecture.id, current_user.org_type)

    return lecture
