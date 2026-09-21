"""AIOS 后端垂直切片（规范 AIOS Master Prompt V1.0）。

本包按规范 §6 分层与 §7 目录树组织；**不修改**既有 `app/` 模块，只通过
`app.main` 挂载 `/api/v1` 路由（规范 §30.1「最小化改动，禁止无故重写已有模块」）。

分层：
    aios/core            配置、错误、日志、ID、DB、响应封装
    aios/contracts       跨模块 DTO 与事件信封
    aios/modules/*       业务模块（audit / jobs / jic / ai_gateway）
    aios/api             /api/v1 路由装配与中间件
"""

__version__ = "1.0.0"
