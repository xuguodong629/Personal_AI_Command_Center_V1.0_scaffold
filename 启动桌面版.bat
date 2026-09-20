@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
title 个人 AI 指挥中心 - 桌面版（开发运行）

where cargo >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Rust 工具链 ^(cargo^)。
  echo.
  echo 请先安装：
  echo   1^) https://win.rustup.rs/x86_64  下载 rustup-init.exe 并安装 ^(默认 MSVC 工具链^)
  echo   2^) 安装 Visual Studio Build Tools，勾选「使用 C++ 的桌面开发」
  echo   安装完成后重开本窗口再试。
  pause
  exit /b 1
)

if not exist node_modules (
  echo 安装前端依赖...
  call npm install
)

echo 启动桌面窗口（首次编译 Rust 约 5-15 分钟，请耐心等待）...
call npm run desktop
pause
