from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from db import get_db
from schemas import MessageCreate
from deps import get_current_user
from datetime import datetime, timezone

router = APIRouter(prefix="/messages", tags=["Messages"])


def _safe_date(val) -> str | None:
    if val is None:
        return None
    if hasattr(val, 'isoformat'):
        return val.isoformat()
    s = str(val)
    return s.replace(' ', 'T') if s else None


def _check_member(db: Session, chat_id: int, user_id: int) -> None:
    row = db.execute(
        text("SELECT 1 FROM chat_members WHERE chat_id = :cid AND user_id = :uid"),
        {"cid": chat_id, "uid": user_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=403, detail="Not a member of this chat")


@router.post("/chat/{chat_id}")
def send_message(
    chat_id: int,
    msg: MessageCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _check_member(db, chat_id, current_user.id)
    try:
        now = datetime.now(timezone.utc)
        now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        result = db.execute(
            text(
                "INSERT INTO messages (content, chat_id, user_id, created_at) "
                "VALUES (:content, :chat_id, :user_id, :created_at) RETURNING id"
            ),
            {
                "content": msg.content,
                "chat_id": chat_id,
                "user_id": current_user.id,
                "created_at": now_str,
            },
        )
        db.commit()
        new_id = result.scalar_one_or_none()
        return {
            "status": "sent",
            "id": new_id,
            "content": msg.content,
            "chat_id": chat_id,
            "user_id": current_user.id,
            "created_at": now.isoformat(),
            "is_read": False,
            "file_url": None,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/{chat_id}")
def get_messages(
    chat_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    _check_member(db, chat_id, current_user.id)
    try:
        for col_sql in [
            "ALTER TABLE messages ADD COLUMN file_url TEXT",
            "ALTER TABLE messages ADD COLUMN is_read INTEGER DEFAULT 0",
        ]:
            try:
                db.execute(text(col_sql))
                db.commit()
            except Exception:
                db.rollback()

        result = db.execute(
            text(
                "SELECT id, content, chat_id, user_id, created_at, "
                "COALESCE(is_read, false) as is_read, file_url "
                "FROM messages WHERE chat_id = :cid ORDER BY id"
            ),
            {"cid": chat_id},
        ).fetchall()

        return [
            {
                "id": r[0],
                "content": r[1],
                "chat_id": r[2],
                "user_id": r[3],
                "created_at": _safe_date(r[4]),
                "is_read": bool(r[5]) if r[5] is not None else False,
                "file_url": r[6],
            }
            for r in result
        ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{message_id}")
def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    msg = db.execute(
        text("SELECT id, user_id FROM messages WHERE id = :id"), {"id": message_id}
    ).fetchone()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg[1] != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        db.execute(text("DELETE FROM messages WHERE id = :id"), {"id": message_id})
        db.commit()
        return {"status": "deleted"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{message_id}/read")
def mark_read(
    message_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        db.execute(
            text("UPDATE messages SET is_read = 1 WHERE id = :id"),
            {"id": message_id},
        )
        db.commit()
        return {"status": "read"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/unread")
def unread_messages(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    try:
        result = db.execute(
            text(
                "SELECT m.id, m.content, m.chat_id, m.user_id, m.created_at "
                "FROM messages m "
                "JOIN chat_members cm ON cm.chat_id = m.chat_id AND cm.user_id = :uid "
                "WHERE m.user_id != :uid AND COALESCE(m.is_read, 0) = 0 "
                "ORDER BY m.id"
            ),
            {"uid": current_user.id},
        ).fetchall()
        return [
            {
                "id": r[0],
                "content": r[1],
                "chat_id": r[2],
                "user_id": r[3],
                "created_at": _safe_date(r[4]),
            }
            for r in result
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
