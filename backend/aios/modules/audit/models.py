"""审计表（规范 §10 / §12.1）：不可变事件——只插入，不更新不删除。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aios.core.db import Base, utc_now


class AuditEvent(Base):
    """不可变审计事件。敏感正文只保存脱敏摘要（规范 §10 末段）。"""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_action_created_at", "action", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), default="", nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    before_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    after_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    request_id: Mapped[str] = mapped_column(String(48), default="", nullable=False, index=True)
    client_summary: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    result: Mapped[str] = mapped_column(String(24), default="ok", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
