"""pytest 公共夹具（规范 §25.1：单元测试无网络、集成测试用隔离数据库）。

关键点：**在导入 aios 之前**设置 DB_URL，否则 Pydantic Settings 会缓存默认值。
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

_TMP_DIR = pathlib.Path(tempfile.mkdtemp(prefix="aios-tests-"))
os.environ.setdefault("DB_URL", f"sqlite+pysqlite:///{(_TMP_DIR / 'aios-test.db').as_posix()}")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("AUTH_REQUIRED", "false")
os.environ.setdefault("AUTH_TOKEN_SHA256", "")
os.environ.setdefault("OTEL_ENABLED", "false")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """用 Alembic 建表（规范 §30.7：不使用 create_all 管理模式）。"""
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def app_client(migrated_database) -> TestClient:
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture()
def client(app_client: TestClient) -> TestClient:
    return app_client


@pytest.fixture()
def tmp_dir() -> pathlib.Path:
    return _TMP_DIR
