@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 个人 AI 指挥中心 - 独立运行

echo ============================================
echo   个人 AI 指挥中心 · AI 猎头中枢
echo   独立运行：不依赖 Dify，无需常驻 Node
echo ============================================
echo.

REM ---------- 1. Python 虚拟环境 ----------
if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/3] 首次运行：创建 Python 虚拟环境...
  py -3.10 -m venv backend\.venv 2>nul
  if not exist "backend\.venv\Scripts\python.exe" (
    python -m venv backend\.venv
  )
  if not exist "backend\.venv\Scripts\python.exe" (
    echo [错误] 创建虚拟环境失败：请先安装 Python 3.10+ ^(确保 py 或 python 命令可用^)
    pause
    exit /b 1
  )
  backend\.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r backend\requirements.txt
)

REM ---------- 2. 前端构建产物 ----------
if not exist "frontend\dist\index.html" (
  echo [2/3] 首次运行：构建前端界面（约 1-3 分钟）...
  pushd frontend
  if not exist "node_modules" call npm install
  call npm run build
  popd
  if not exist "frontend\dist\index.html" (
    echo [错误] 前端构建失败：请确认已安装 Node.js 18+，
    echo        然后手动执行： cd frontend ^&^& npm install ^&^& npm run build
    pause
    exit /b 1
  )
)

REM ---------- 3. 启动服务 ----------
echo [3/3] 启动服务：http://127.0.0.1:8787
echo     关闭本窗口即停止服务
echo.
start "" http://127.0.0.1:8787
pushd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8787
popd
pause
