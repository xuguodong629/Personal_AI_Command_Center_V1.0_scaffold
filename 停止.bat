@echo off
chcp 65001 >nul
echo 正在停止 8787 端口上的「个人 AI 指挥中心」...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8787" ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>nul
echo 已停止（若启动窗口仍在，直接关闭即可）。
pause
