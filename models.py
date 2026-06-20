from sqlalchemy import (
    String, Integer, Boolean, ForeignKey, Column, Text, DateTime, Table
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from db import Base

post_enrollments = Table(
    "post_enrollments",
    Base.metadata,
    Column("post_id", Integer, ForeignKey("posts.id", ondelete="CASCADE")),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE")),
)

class_members = Table(
    "class_members",
    Base.metadata,
    Column("class_id", Integer, ForeignKey("classes.id", ondelete="CASCADE")),
    Column("user_id",  Integer, ForeignKey("users.id",  ondelete="CASCADE")),
)

chat_members = Table(
    "chat_members",
    Base.metadata,
    Column("chat_id", Integer, ForeignKey("chats.id")),
    Column("user_id", Integer, ForeignKey("users.id")),
)

class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    group: Mapped[str] = mapped_column(String(100), nullable=True)

    org_type: Mapped[str] = mapped_column(String, nullable=False, default="university")

    creator: Mapped["User"] = relationship(back_populates="classes_created", foreign_keys=[created_by])
    members: Mapped[list["User"]] = relationship(
        "User",
        secondary=class_members,
        back_populates="classes",
    )

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="student", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=True)
    group: Mapped[str] = mapped_column(String(100), nullable=True)
    org_type: Mapped[str] = mapped_column(String, nullable=False, default="university")

    posts: Mapped[list["Posts"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    chats: Mapped[list["Chat"]] = relationship(
        "Chat",
        secondary=chat_members,
        back_populates="members",
    )
    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
    )
    assignments_created: Mapped[list["Assignment"]] = relationship(
        back_populates="creator",
        cascade="all, delete-orphan",
        foreign_keys="Assignment.created_by",
    )
    classes_created: Mapped[list["Class"]] = relationship(
        back_populates="creator",
        cascade="all, delete-orphan",
        foreign_keys="Class.created_by",
    )
    classes: Mapped[list["Class"]] = relationship(
        "Class",
        secondary=class_members,
        back_populates="members",
    )

class Posts(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    user: Mapped["User"] = relationship(back_populates="posts")

class Chat(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    members: Mapped[list["User"]] = relationship(
        "User",
        secondary=chat_members,
        back_populates="chats",
    )

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    chat_id = Column(Integer, ForeignKey("chats.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    is_read = Column(Boolean, default=False)
    file_url = Column(String, nullable=True)

class Reaction(Base):
    __tablename__ = "reactions"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    emoji = Column(String)

class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    class_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, server_default="0")
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    criteria: Mapped[str] = mapped_column(Text, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, default=100)
    deadline: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    reference_solution_url: Mapped[str] = mapped_column(String, nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    creator: Mapped["User"] = relationship(back_populates="assignments_created", foreign_keys=[created_by])

    submissions: Mapped[list["Submission"]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
    )
    variants: Mapped[list["AssignmentVariant"]] = relationship(
        back_populates="assignment",
        cascade="all, delete-orphan",
        order_by="AssignmentVariant.variant_number",
    )

class AssignmentVariant(Base):
    __tablename__ = "assignment_variants"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=True)
    reference_solution_url: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    assignment: Mapped["Assignment"] = relationship(back_populates="variants")

class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    file_url: Mapped[str] = mapped_column(String, nullable=True)
    file_urls: Mapped[str] = mapped_column(Text, nullable=True)
    text_content: Mapped[str] = mapped_column(Text, nullable=True)
    variant_number: Mapped[int] = mapped_column(Integer, nullable=True)

    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String, default="submitted")

    assignment: Mapped["Assignment"] = relationship(back_populates="submissions")
    student: Mapped["User"] = relationship(back_populates="submissions")
    grade: Mapped["Grade"] = relationship(
        back_populates="submission",
        uselist=False,
        cascade="all, delete-orphan",
    )

    from typing import ClassVar
    student_name: ClassVar[str] = None

class Grade(Base):
    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id"), nullable=False, unique=True
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback: Mapped[str] = mapped_column(Text, nullable=True)
    criteria_scores: Mapped[str] = mapped_column(Text, nullable=True)
    graded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    graded_by: Mapped[str] = mapped_column(String, default="ai")

    submission: Mapped["Submission"] = relationship(back_populates="grade")

EMBED_DIM = 1536

class RagDocument(Base):
    __tablename__ = "rag_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    org_type: Mapped[str] = mapped_column(String, nullable=False, default="university")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    chunks: Mapped[list["RagChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

class RagChunk(Base):
    __tablename__ = "rag_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped["RagDocument"] = relationship(back_populates="chunks")

class AiUsageLog(Base):
    __tablename__ = "ai_usage_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    class_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(64), nullable=False)
    org_type: Mapped[str] = mapped_column(String, nullable=False, default="university")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ProcessedDocument(Base):
    __tablename__ = "processed_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    rag_document_id: Mapped[int] = mapped_column(
        ForeignKey("rag_documents.id", ondelete="CASCADE"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ──────────────────────────────────────────────────────────────────
#  AI-аватар преподавателя (читает лекции)
# ──────────────────────────────────────────────────────────────────

class TeacherAvatar(Base):
    """
    Один аватар на учителя. Создаётся один раз: фото + образец голоса.
    Требует одобрения админа (затратная фича — голос/видео платные).
    """
    __tablename__ = "teacher_avatars"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    teacher_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    org_type: Mapped[str] = mapped_column(String, nullable=False, default="university")

    display_name: Mapped[str] = mapped_column(String(200), nullable=True)
    photo_url: Mapped[str] = mapped_column(String, nullable=True)
    voice_sample_url: Mapped[str] = mapped_column(String, nullable=True)

    elevenlabs_voice_id: Mapped[str] = mapped_column(String(128), nullable=True)
    did_presenter_id: Mapped[str] = mapped_column(String(128), nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=True)
    voice_clone_warning: Mapped[str] = mapped_column(Text, nullable=True)

    reviewed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])

    lectures: Mapped[list["AvatarLecture"]] = relationship(
        back_populates="avatar",
        cascade="all, delete-orphan",
    )


class AvatarLecture(Base):
    """
    Лекция, начитанная аватаром по презентации/документу учителя.
    Каждая новая лекция требует одобрения админа (расходует платные минуты/символы).
    """
    __tablename__ = "avatar_lectures"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    avatar_id: Mapped[int] = mapped_column(
        ForeignKey("teacher_avatars.id", ondelete="CASCADE"), nullable=False, index=True
    )
    class_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    org_type: Mapped[str] = mapped_column(String, nullable=False, default="university")

    title: Mapped[str] = mapped_column(String(256), nullable=False)

    source_filename: Mapped[str] = mapped_column(String(512), nullable=True)
    source_file_url: Mapped[str] = mapped_column(String, nullable=True)

    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    style: Mapped[str] = mapped_column(String(32), nullable=False, default="university")

    auto_summary: Mapped[bool] = mapped_column(Boolean, default=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_approval")
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)

    reviewed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    summary_text: Mapped[str] = mapped_column(Text, nullable=True)
    intro_video_url: Mapped[str] = mapped_column(String, nullable=True)

    estimated_chars: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    avatar: Mapped["TeacherAvatar"] = relationship(back_populates="lectures")
    slides: Mapped[list["AvatarLectureSlide"]] = relationship(
        back_populates="lecture",
        cascade="all, delete-orphan",
        order_by="AvatarLectureSlide.slide_index",
    )


class AvatarLectureSlide(Base):
    """Один слайд лекции: картинка слайда + текст рассказа аватара + готовое аудио."""
    __tablename__ = "avatar_lecture_slides"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    lecture_id: Mapped[int] = mapped_column(
        ForeignKey("avatar_lectures.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slide_index: Mapped[int] = mapped_column(Integer, nullable=False)

    slide_image_url: Mapped[str] = mapped_column(String, nullable=True)
    slide_source_text: Mapped[str] = mapped_column(Text, nullable=True)

    narration_text: Mapped[str] = mapped_column(Text, nullable=True)
    audio_url: Mapped[str] = mapped_column(String, nullable=True)
    audio_duration_seconds: Mapped[float] = mapped_column(Integer, nullable=True)

    lecture: Mapped["AvatarLecture"] = relationship(back_populates="slides")