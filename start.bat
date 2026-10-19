@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=python"
if exist "venv\Scripts\python.exe" set "PY=venv\Scripts\python.exe"

if not exist "venv\Scripts\python.exe" (
    echo 首次运行，正在安装依赖（需要联网）...
    python -m pip install -r requirements.txt -q
)

echo 启动智卷（桌面窗口）...
"%PY%" app.py
pause
