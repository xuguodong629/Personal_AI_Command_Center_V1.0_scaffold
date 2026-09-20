@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 安装抓取增强依赖

echo ============================================
echo   抓取增强依赖安装（公开页正文抓取）
echo ============================================
echo.

if not exist "backend\.venv\Scripts\python.exe" (
  echo [错误] 未找到 backend\.venv，请先双击 启动.bat 完成初始化。
  pause
  exit /b 1
)

echo [1/3] 安装轻量抓取依赖 trafilatura（必需，体积小）...
backend\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q trafilatura
if errorlevel 1 (
  echo [警告] trafilatura 安装失败，抓取会退化为正则提取。
)

echo.
echo [2/3] 安装免 Key 检索依赖 ddgs（DuckDuckGo，无需注册，搜索额度用尽时用它）...
backend\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q ddgs
if errorlevel 1 (
  echo [警告] ddgs 安装失败，免 Key 检索不可用（其余引擎不受影响）。
)

echo.
choice /c YN /m "是否继续安装 crawl4ai（可选，支持 JS 渲染，约 150-300MB）"
if errorlevel 2 goto done

echo [3/3] 安装 crawl4ai + Chromium 浏览器...
backend\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q crawl4ai
backend\.venv\Scripts\python.exe -m playwright install chromium

:done
echo.
echo 完成。抓取器选择：设置 → 模型直连 → 正文抓取器
echo   auto（默认，装了 crawl4ai 就优先用它）/ http（轻量）/ crawl4ai
echo.
echo 搜索引擎选择：设置 → 搜索引擎
echo   ddg = 免 Key（推荐先试这个）/ tavily / 智谱 / serper / brave / 博查 / searxng / mcp
pause
