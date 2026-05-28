import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class QALog(Base):
    __tablename__ = "qa_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[dict]] = mapped_column(JSON, default=list)
    user_feedback: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    feedback_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

