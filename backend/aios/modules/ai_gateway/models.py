"""AI 表（规范 §12.2 / §21.1）：模型目录 + 调用账本。正文不保存，只存哈希与元数据。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from aios.core.db import Base, utc_now


class AIModel(Base):
    """已配置模型目录（provider/model/capabilities）。"""

    __tablename__ = "ai_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(96), nullable=False)
    capabilities: Mapped[str] = mapped_column(String(255), default="chat", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AIRun(Base):
    """每次模型调用账本（规范 §21.1）：可回答"谁/为何/花了多少/结果如何"。"""

    __tablename__ = "ai_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), default="", nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider: Mapped[str] = mapped_column(String(48), default="", nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    purpose: Mapped[str] = mapped_column(String(48), default="", nullable=False, index=True)
    prompt_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    schema_version: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="running", nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    token_usage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    trace_id: Mapped[str] = mapped_column(String(48), default="", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
