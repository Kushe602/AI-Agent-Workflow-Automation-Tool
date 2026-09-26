"""Database models: users, agent runs, and the ordered steps within each run."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    # Python-side default keeps microsecond precision so steps sort deterministically
    # (SQLite's CURRENT_TIMESTAMP is only second-precision).
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(default=_now)

    runs: Mapped[list["Run"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    goal: Mapped[str] = mapped_column(Text)
    # pending | running | succeeded | failed | stopped
    status: Mapped[str] = mapped_column(String(20), default="pending")
    model: Mapped[str] = mapped_column(String(80), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)

    owner: Mapped["User"] = relationship(back_populates="runs")
    steps: Mapped[list["Step"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="Step.idx"
    )


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    # thinking | tool_call | tool_result | final | error
    type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(80), nullable=True)  # tool name
    content: Mapped[str] = mapped_column(Text, default="")
    tool_input: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON blob
    created_at: Mapped[datetime] = mapped_column(default=_now)

    run: Mapped["Run"] = relationship(back_populates="steps")
