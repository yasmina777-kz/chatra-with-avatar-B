import json
from fastapi import APIRouter, WebSocket, Query, HTTPException
from starlette.websockets import WebSocketDisconnect
from sqlalchemy.orm import Session
from db import SessionLocal
from security import decode_token
from crud import users as crud_users

router = APIRouter()

connections: dict[int, list[WebSocket]] = {}

async def _authenticate(token: str, chat_id: int) -> int | None:
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub", 0))
        if not user_id:
            return None
        db: Session = SessionLocal()
        try:
            user = crud_users.get_user_by_id(db, user_id)
            if not user or not user.is_active:
                return None
            from sqlalchemy import text
            row = db.execute(
                text("SELECT 1 FROM chat_members WHERE chat_id = :cid AND user_id = :uid"),
                {"cid": chat_id, "uid": user_id},
            ).fetchone()
            if not row:
                return None
            return user_id
        finally:
            db.close()
    except Exception:
        return None

@router.websocket("/ws/{chat_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    chat_id: int,
    token: str = Query(...),
):
    user_id = await _authenticate(token, chat_id)
    if not user_id:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    connections.setdefault(chat_id, []).append(websocket)

    try:
        while True:
            raw = await websocket.receive_text()

            dead = []
            for conn in connections.get(chat_id, []):
                try:
                    await conn.send_text(raw)
                except Exception:
                    dead.append(conn)

            for d in dead:
                try:
                    connections[chat_id].remove(d)
                except ValueError:
                    pass

    except WebSocketDisconnect:
        try:
            connections[chat_id].remove(websocket)
        except (ValueError, KeyError):
            pass
