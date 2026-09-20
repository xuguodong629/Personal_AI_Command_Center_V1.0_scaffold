@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 安装语音依赖（本地 Whisper 识别 + edge-tts 合成）

echo ============================================
echo   模拟面试语音依赖安装
echo   · faster-whisper  本地语音识别（离线、免费）
echo   · edge-tts        中文语音合成（免费）
echo ============================================
echo.

if not exist "backend\.venv\Scripts\python.exe" (
  echo [错误] 未找到 backend\.venv，请先双击 启动.bat 完成初始化。
  pause
  exit /b 1
)

echo [1/2] 安装依赖（约 300MB，走阿里云镜像加速）...
backend\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com faster-whisper edge-tts
if errorlevel 1 (
  echo.
  echo [错误] 依赖安装失败，可稍后重试或换镜像源。
  pause
  exit /b 1
)

echo.
echo [2/2] 完成。
echo   · Whisper 模型首次使用会自动下载（small 约 500MB），默认走 hf-mirror 镜像，
echo     存放在项目内 data\models\whisper（可整体拷贝迁移）。
echo   · 验证：浏览器打开 http://127.0.0.1:8787/api/voice/status
echo         应看到 stt/tts 均为 available:true
echo   · 语音对话在「模拟面试」页：勾选「面试官语音播报」，点「语音回答」开始/结束录音。
pause
