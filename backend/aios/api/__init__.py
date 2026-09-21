"""AIOS v1 切片的 FastAPI 装配入口。"""
from __future__ import annotations

from aios.api.v1 import build_router, install  # noqa: F401

__all__ = ["build_router", "install"]
