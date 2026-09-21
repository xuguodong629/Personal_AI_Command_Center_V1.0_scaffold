"""配置（规范 §8）：按域划分的 Pydantic Settings，启动时校验，密钥只进基础设施层。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/aios/core/config.py → 仓库根
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"


class AppSettings(BaseSettings):
    """APP_*：进程与运行环境。"""

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=str(ENV_FILE), extra="ignore")

    env: str = "local"
    name: str = "aios"
    host: str = "127.0.0.1"
    port: int = 8787
    log_level: str = "INFO"
    standalone: bool = True


class DBSettings(BaseSettings):
    """DB_*：主数据库。默认 SQLite（本地一键）；置 DB_URL 即切 PostgreSQL 16。"""

    model_config = SettingsConfigDict(env_prefix="DB_", env_file=str(ENV_FILE), extra="ignore")

    url: str = Field(default=f"sqlite+pysqlite:///{(DATA_DIR / 'aios.db').as_posix()}")
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 5

    @property
    def is_sqlite(self) -> bool:
        return self.url.startswith("sqlite")


class AuthSettings(BaseSettings):
    """AUTH_*：单用户本地账户（规范 §10）。只存令牌哈希，不存明文。"""

    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=str(ENV_FILE), extra="ignore")

    required: bool = False
    token_sha256: str = ""
    default_actor: str = "local-user"
    default_workspace: str = "local-workspace"


class AISettings(BaseSettings):
    """AI_*：AI Gateway 的路由与预算（规范 §21）。"""

    model_config = SettingsConfigDict(env_prefix="AI_", env_file=str(ENV_FILE), extra="ignore")

    purpose_model: str = ""          # 形如 "job_summary=deepseek-chat;job_extraction=deepseek-chat"
    monthly_budget_cny: float = 0.0
    timeout_seconds: float = 120.0
    max_retries: int = 2
    cache_enabled: bool = True


class JICSettings(BaseSettings):
    """JIC_*：来源准入与来源预算默认值（规范 §14.1 / §19）。"""

    model_config = SettingsConfigDict(env_prefix="JIC_", env_file=str(ENV_FILE), extra="ignore")

    default_rate_limit_per_minute: int = 6
    default_rate_limit_per_hour: int = 120
    default_daily_budget: int = 600
    default_max_page_depth: int = 3
    default_max_consecutive_failures: int = 3
    default_retention_days: int = 14
    allow_auto_crawl: bool = False


class OtelSettings(BaseSettings):
    """OTEL_*：观测（规范 §22）。未启用时 trace_id 仍生成并透传日志。"""

    model_config = SettingsConfigDict(env_prefix="OTEL_", env_file=str(ENV_FILE), extra="ignore")

    enabled: bool = False
    service_name: str = "aios-api"
    exporter_otlp_endpoint: str = ""


class Settings:
    """聚合视图；`get_settings()` 返回单例。"""

    def __init__(self) -> None:
        self.app = AppSettings()
        self.db = DBSettings()
        self.auth = AuthSettings()
        self.ai = AISettings()
        self.jic = JICSettings()
        self.otel = OtelSettings()

    def purpose_model(self) -> dict[str, str]:
        """把 `purpose=model;...` 解析成 {purpose: model}。"""
        out: dict[str, str] = {}
        for part in (self.ai.purpose_model or "").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out

    def validate(self) -> list[str]:
        """启动时校验（规范 §28）：返回告警列表；硬错误直接抛。"""
        warnings: list[str] = []
        if self.auth.required and not self.auth.token_sha256:
            raise RuntimeError("AUTH_REQUIRED=true 但 AUTH_TOKEN_SHA256 为空：请先执行 python -m aios.cli issue-token")
        if not self.db.url:
            raise RuntimeError("DB_URL 为空")
        if self.db.is_sqlite and self.app.env == "production":
            warnings.append("生产环境使用 SQLite：规范 §4 建议 PostgreSQL 16（见 docs/adr）")
        if not self.auth.required:
            warnings.append("AUTH_REQUIRED=false：仅适用于本机回环访问（规范 §10 要求至少单用户本地账户）")
        if not self.otel.enabled:
            warnings.append("OTEL_ENABLED=false：追踪未导出，仅日志透传 trace_id（规范 §22.3）")
        return warnings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
