"""Alembic 环境（规范 §11.8）：数据库 URL 来自 AIOS 配置；导入全部模型供 autogenerate 使用。"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from aios.core.config import get_settings
from aios.core.db import Base

# 必须导入所有模型模块，autogenerate 才能看到全部表
from aios.core import outbox  # noqa: F401
from aios.modules.ai_gateway import models as ai_models  # noqa: F401
from aios.modules.audit import models as audit_models  # noqa: F401
from aios.modules.jic import models as jic_models  # noqa: F401
from aios.modules.jobs import models as job_models  # noqa: F401
from aios.modules.platform import models as platform_models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return get_settings().db.url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      compare_type=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
