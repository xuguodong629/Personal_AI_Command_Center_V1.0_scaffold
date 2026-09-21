"""Outbox（规范 §13）：业务数据与事件在同一事务写入，发布器随后投递；消费方按 event_id 去重。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from aios.contracts import EventEnvelope
from aios.core.db import Base, utc_now
from aios.core.ids import new_uuid


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


def enqueue(session: Session, event: EventEnvelope) -> OutboxEvent:
    """在**当前事务内**写入事件（调用方负责 commit）。"""
    row = OutboxEvent(
        id=event.event_id,
        event_type=event.event_type,
        aggregate_type=event.aggregate.get("type", ""),
        aggregate_id=event.aggregate.get("id", ""),
        payload=event.model_dump_json(),
        occurred_at=event.occurred_at,
    )
    session.add(row)
    return row


def take_unpublished(session: Session, limit: int = 50) -> list[OutboxEvent]:
    """发布器（本切片进程内轮询）取待发布事件；投递成功后调用 mark_published。"""
    return (session.query(OutboxEvent)
            .filter(OutboxEvent.published.is_(False))
            .order_by(OutboxEvent.occurred_at)
            .limit(limit).all())


def mark_published(session: Session, event_id: str) -> None:
    row = session.get(OutboxEvent, event_id)
    if row is not None:
        row.published = True
        row.published_at = utc_now()


def new_aggregate(aggregate_type: str, aggregate_id: str | None = None) -> dict[str, str]:
    return {"type": aggregate_type, "id": aggregate_id or new_uuid()}
