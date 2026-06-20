import json
from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session
from models import Assignment, Submission, Grade

def create_assignment(
    db: Session,
    class_id: int,
    title: str,
    description: Optional[str],
    criteria: list,
    max_score: int,
    deadline: Optional[datetime],
    created_by: int,
    reference_solution_url: Optional[str] = None,
) -> Assignment:
    obj = Assignment(
        class_id=class_id,
        title=title,
        description=description,
        criteria=json.dumps(criteria, ensure_ascii=False),
        max_score=max_score,
        deadline=deadline,
        created_by=created_by,
        reference_solution_url=reference_solution_url,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def get_assignment(db: Session, assignment_id: int) -> Optional[Assignment]:
    return db.query(Assignment).filter(Assignment.id == assignment_id).first()

def get_all_assignments(db: Session, class_id: Optional[int] = None, active_only: bool = False) -> List[Assignment]:
    q = db.query(Assignment)
    if class_id is not None:
        q = q.filter(Assignment.class_id == class_id)
    if active_only:
        q = q.filter(Assignment.is_active == True)
    return q.order_by(Assignment.created_at.desc()).all()

def update_assignment(db: Session, assignment_id: int, data: dict) -> Optional[Assignment]:
    obj = get_assignment(db, assignment_id)
    if not obj:
        return None
    if "criteria" in data and isinstance(data["criteria"], list):
        data["criteria"] = json.dumps(data["criteria"], ensure_ascii=False)
    for key, value in data.items():
        if value is not None:
            setattr(obj, key, value)
    db.commit()
    db.refresh(obj)
    return obj

def delete_assignment(db: Session, assignment_id: int) -> bool:
    obj = get_assignment(db, assignment_id)
    if not obj:
        return False
    db.delete(obj)
    db.commit()
    return True

def create_submission(
    db: Session,
    assignment_id: int,
    student_id: int,
    text_content: Optional[str],
    file_url: Optional[str],
    file_urls: Optional[list] = None,
    is_late: bool = False,
) -> Submission:
    status = "late" if is_late else "submitted"
    obj = Submission(
        assignment_id=assignment_id,
        student_id=student_id,
        text_content=text_content,
        file_url=file_url,
        file_urls=json.dumps(file_urls, ensure_ascii=False) if file_urls else None,
        status=status,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def get_submission(db: Session, submission_id: int) -> Optional[Submission]:
    return db.query(Submission).filter(Submission.id == submission_id).first()

def get_submissions_for_assignment(db: Session, assignment_id: int) -> List[Submission]:
    return (
        db.query(Submission)
        .filter(Submission.assignment_id == assignment_id)
        .order_by(Submission.submitted_at.desc())
        .all()
    )

def get_submissions_for_student(db: Session, student_id: int) -> List[Submission]:
    return (
        db.query(Submission)
        .filter(Submission.student_id == student_id)
        .order_by(Submission.submitted_at.desc())
        .all()
    )

def delete_submission(db: Session, submission_id: int, student_id: int) -> bool:
    obj = (
        db.query(Submission)
        .filter(Submission.id == submission_id, Submission.student_id == student_id)
        .first()
    )
    if not obj:
        return False
    if obj.status in ("graded",):
        return False
    db.query(Grade).filter(Grade.submission_id == submission_id).delete()
    db.delete(obj)
    db.commit()
    return True

def student_already_submitted(db: Session, assignment_id: int, student_id: int) -> bool:
    return (
        db.query(Submission)
        .filter(
            Submission.assignment_id == assignment_id,
            Submission.student_id == student_id,
        )
        .first()
        is not None
    )

def set_submission_status(db: Session, submission_id: int, status: str) -> Optional[Submission]:
    obj = get_submission(db, submission_id)
    if not obj:
        return None
    obj.status = status
    db.commit()
    db.refresh(obj)
    return obj

def create_or_update_grade(
    db: Session,
    submission_id: int,
    score: int,
    feedback: Optional[str],
    criteria_scores: Optional[list],
    graded_by: str = "ai",
) -> Grade:
    existing = db.query(Grade).filter(Grade.submission_id == submission_id).first()
    criteria_json = json.dumps(criteria_scores, ensure_ascii=False) if criteria_scores else None

    if existing:
        existing.score = score
        existing.feedback = feedback
        existing.criteria_scores = criteria_json
        existing.graded_by = graded_by
        existing.graded_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    grade = Grade(
        submission_id=submission_id,
        score=score,
        feedback=feedback,
        criteria_scores=criteria_json,
        graded_by=graded_by,
    )
    db.add(grade)
    db.commit()
    db.refresh(grade)
    return grade

def get_grade_by_submission(db: Session, submission_id: int) -> Optional[Grade]:
    return db.query(Grade).filter(Grade.submission_id == submission_id).first()
