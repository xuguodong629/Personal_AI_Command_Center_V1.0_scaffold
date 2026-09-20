@echo off
chcp 65001 >nul
cd /d "%~dp0frontend"
title 个人 AI 指挥中心 - 打包桌面版

where cargo >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Rust 工具链 ^(cargo^)，请先安装 rustup + VS Build Tools（见 启动桌面版.bat 提示）。
  pause
  exit /b 1
)

if not exist node_modules call npm install

echo 正在打包（首次约 10-20 分钟）...
call npm run desktop:build
if errorlevel 1 (
  echo [错误] 打包失败，请把上面的报错贴回来。
  pause
  exit /b 1
)

echo.
echo 打包完成，安装包位于：
echo   frontend\src-tauri\target\release\bundle\nsis\
echo 注意：绿色运行需保证 exe 所在目录旁存在 backend\ 目录（含 .venv 与项目数据）。
pause
