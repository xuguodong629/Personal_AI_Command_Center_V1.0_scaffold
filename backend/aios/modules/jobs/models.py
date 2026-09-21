"""调度与作业执行表（规范 §12.1 / §19）：幂等键、重试、执行追踪。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from aios.core.db import Base
from aios.core.mixins import TimestampMixin


class ScheduledJob(Base, TimestampMixin):
    """声明式调度定义（规范 §19.1）。misfire 策略不允许默认无限补跑。"""

    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    cron_expr: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    misfire_policy: Mapped[str] = mapped_column(String(24), default="skip", nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobExecution(Base, TimestampMixin):
    """一次执行实例（规范 §19.1/§19.3）。幂等键 = job_type + 调用方提供的 key。"""

    __tablename__ = "job_executions"
    __table_args__ = (
        UniqueConstraint("job_type", "idempotency_key", name="uq_job_executions_job_type_idempotency_key"),
        Index("ix_job_executions_status_queued_at", "status", "queued_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), default="", nullable=False)
    input_ref: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    output_ref: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_code: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    queue: Mapped[str] = mapped_column(String(24), default="default", nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
