from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db import get_db
from models import Reaction
from deps import get_current_user

router = APIRouter(prefix="/reactions", tags=["Reactions"])

@router.post("/{message_id}")
def add_reaction(
    message_id: int,
    emoji: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    existing = (
        db.query(Reaction)
        .filter(Reaction.message_id == message_id, Reaction.user_id == current_user.id)
        .first()
    )
    if existing:
        existing.emoji = emoji
        db.commit()
        db.refresh(existing)
        return existing

    reaction = Reaction(message_id=message_id, user_id=current_user.id, emoji=emoji)
    db.add(reaction)
    db.commit()
    db.refresh(reaction)
    return reaction

@router.delete("/{message_id}")
def remove_reaction(
    message_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    deleted = (
        db.query(Reaction)
        .filter(Reaction.message_id == message_id, Reaction.user_id == current_user.id)
        .delete()
    )
    db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Reaction not found")
    return {"status": "removed"}

@router.get("/{message_id}")
def get_reactions(
    message_id: int,
    db: Session = Depends(get_db),
):
    reactions = db.query(Reaction).filter(Reaction.message_id == message_id).all()
    return [
        {"id": r.id, "message_id": r.message_id, "user_id": r.user_id, "emoji": r.emoji}
        for r in reactions
    ]
