#!/usr/bin/env bash
# 智卷 · macOS / Linux 启动脚本
set -e
cd "$(dirname "$0")"

PY=python3
if [ -x "venv/bin/python" ]; then
    PY=venv/bin/python
else
    echo "首次运行，正在安装依赖（需要联网）..."
    "$PY" -m pip install -r requirements.txt -q
fi

echo "启动智卷..."
exec "$PY" app.py
