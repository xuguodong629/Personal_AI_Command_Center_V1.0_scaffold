"""Spider 内置实现与注册（规范 §14.2 目录规范）。import 本包即完成注册。"""
from __future__ import annotations

from aios.modules.jic.infrastructure.spiders import custom_spider, official_company, public_html, rss
from aios.modules.jic.infrastructure.spiders.base import FETCH_UA, Spider, detect_block, strip_html
from aios.modules.jic.infrastructure.spiders.manager import SpiderManager
from aios.modules.jic.infrastructure.spiders.manager import manager as spider_manager

# 内置 Spider 注册到 SpiderManager（应用层只依赖 spider_manager 单例）
spider_manager.register(public_html.PublicHtmlSpider)
spider_manager.register(official_company.OfficialCompanySpider)
spider_manager.register(rss.RssSpider)
spider_manager.register(custom_spider.CustomSpider)

__all__ = ["FETCH_UA", "Spider", "SpiderManager", "detect_block", "spider_manager", "strip_html"]

