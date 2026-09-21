"""ORM 公共 Mixin（规范 §11.3）：每张可变业务表至少含 created_at/updated_at/created_by/updated_by。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from aios.core.db import utc_now


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now,
                                                 onupdate=utc_now, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class SoftDeleteMixin:
    """软删除 + 受控后台清除（规范 §23.7）。"""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
