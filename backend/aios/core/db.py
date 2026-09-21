"""数据库（规范 §11 / §30.7）：SQLAlchemy 2.x + Alembic 管理模式，运行时绝不 create_all。

默认 SQLite（本地一键）；把 DB_URL 换成 postgresql+psycopg://... 即可切 PostgreSQL 16。
"""
from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from aios.core.config import get_settings


def utc_now():
    """所有时间以 UTC 写入（规范 §11.4）。"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        kwargs: dict = {"echo": settings.db.echo, "future": True}
        if settings.db.is_sqlite:
            # SQLite：内存库需同一连接；文件库需允许跨线程（后台作业运行在线程里）
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in settings.db.url:
                kwargs["poolclass"] = StaticPool
        else:
            kwargs["pool_size"] = settings.db.pool_size
            kwargs["max_overflow"] = settings.db.max_overflow
        _engine = create_engine(settings.db.url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_session() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个会话，异常回滚。"""
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """后台作业/脚本用：事务边界 = 应用服务边界（规范 §6.1）。"""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """测试用：丢弃缓存引擎与连接池。"""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
