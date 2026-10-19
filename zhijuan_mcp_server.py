import os
import sys
import time
import subprocess
import requests
import atexit
from mcp.server.mcpserver import MCPServer
mcp = MCPServer("ZhijuanToolkit")

# 👇 新增：动态读取环境变量中的端口，默认 5001
PORT = os.environ.get("PORT", 5001)
ZHIJUAN_BASE = f"http://127.0.0.1:{PORT}"
ZHIJUAN_API = f"{ZHIJUAN_BASE}/api"

# 记录后台拉起的 Flask 进程
_flask_process = None


def cleanup_flask_process():
    """在 MCP 退出时，强制杀掉后台拉起的 Flask 进程，防止变成僵尸进程占用端口"""
    global _flask_process
    if _flask_process and _flask_process.poll() is None:
        sys.stderr.write("[MCP] 正在关闭后台 Flask 服务...\n")
        try:
            if sys.platform == "win32":
                # Windows 下强制结束进程树
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(_flask_process.pid)], capture_output=True)
            else:
                _flask_process.terminate()
        except Exception as e:
            sys.stderr.write(f"[MCP] 关闭 Flask 失败: {e}\n")


# 注册退出清理函数
atexit.register(cleanup_flask_process)


def ensure_flask_running():
    """检查 Flask 后台是否在运行，如果没运行就在后台静默拉起它"""
    global _flask_process
    try:
        requests.get(f"{ZHIJUAN_BASE}/", timeout=1, proxies={"http": None, "https": None})
        sys.stderr.write("[MCP] 智卷 Flask 后台已在运行。\n")
        return True
    except requests.exceptions.ConnectionError:
        sys.stderr.write("[MCP] 检测到 Flask 未启动，正在后台自动拉起...\n")

        current_dir = os.path.dirname(os.path.abspath(__file__))
        app_path = os.path.join(current_dir, "app.py")

        if not os.path.exists(app_path):
            sys.stderr.write(f"[MCP] 错误：找不到 {app_path}\n")
            return False

        # 👇 这里是外层 try，负责捕获 Popen 启动失败
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            if sys.platform == "win32":
                _flask_process = subprocess.Popen(
                    [sys.executable, app_path],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    cwd=current_dir,
                    env=env,
                    shell=False
                )
            else:
                _flask_process = subprocess.Popen(
                    [sys.executable, app_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=current_dir,
                    env=env,
                    shell=False
                )

            time.sleep(3.5)

            # 👇 这里是内层 try，负责捕获 健康检查 失败（端口占用）
            try:
                requests.get(f"{ZHIJUAN_BASE}/", timeout=2, proxies={"http": None, "https": None})
                sys.stderr.write("[MCP] Flask 后台拉起成功。\n")
                return True
            except requests.exceptions.ConnectionError:
                sys.stderr.write(f"[MCP] 错误：Flask 启动失败。可能是 {PORT} 端口被占用，请检查。\n")
                return False

        # 👇 这个 except 属于最上面的外层 try
        except Exception as e:
            sys.stderr.write(f"[MCP] 自动拉起 Flask 失败: {e}\n")
            return False


@mcp.tool()
def parse_document(file_path: str) -> str:
    """
    调用智卷本地引擎，将文档解析为标准题库 JSON。
    支持格式：.docx, .pdf
    """
    if not os.path.exists(file_path):
        return f"File not found: {file_path}"

    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            res = requests.post(
                f"{ZHIJUAN_API}/parse_file",
                files=files,
                timeout=120,
                proxies={"http": None, "https": None}
            )
            data = res.json()

            if data.get("ok"):
                return f"Success! Extracted {data['count']} questions."
            else:
                return f"解析失败：{data.get('msg')}"
    except Exception as e:
        return f"连接智卷引擎失败，请确保 Flask 已启动。错误：{e}"


@mcp.tool()
def generate_ai_paper(file_path: str, mode: str = "reading", count: int = 4) -> str:
    """
    调用智卷 AI 引擎，从长文档中一键生成试卷，并返回 Word 下载链接。

    Args:
        file_path: 长文档的本地绝对路径
        mode: 题型，可选 "reading" (阅读理解) 或 "cloze" (完形填空)
        count: 题目数量，默认 4 题
    """
    if not os.path.exists(file_path):
        return f"文件不存在: {file_path}"

    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            data = {"mode": mode, "subject": "auto", "difficulty": "normal", "count": count}
            res = requests.post(
                f"{ZHIJUAN_API}/generate_ai_paper",
                files=files,
                data=data,
                timeout=180,
                proxies={"http": None, "https": None}
            )
            result = res.json()

            if result.get("ok"):
                sid = result.get("sid")

                # 构建 DSH 能识别的 Markdown 格式返回内容
                download_url = f"{ZHIJUAN_BASE}/export_reading_word/{sid}"

                md_text = f"✅ **AI 试卷生成成功！**\n\n"
                md_text += f"### 📄 下载试卷\n"
                md_text += f"👉 **[点击此处下载 Word 文档]({download_url})**\n\n"
                md_text += f"> 💡 提示：下载后您可以直接在 Word 中修改或打印。如果需要调整排版，请打开 [智卷 Web 界面]({ZHIJUAN_BASE}/reading/{sid}) 进行可视化设置。"

                return md_text
            else:
                return f"生成失败：{result.get('msg')}"
    except Exception as e:
        return f"连接智卷 AI 引擎失败。错误：{e}"


@mcp.tool()
def get_today_review_count() -> str:
    """获取智卷今日需要复习的错题数量"""
    try:
        res = requests.get(
            f"{ZHIJUAN_API}/dashboard_stats",
            timeout=5,
            proxies={"http": None, "https": None}
        )
        data = res.json()
        if data.get("ok"):
            return f"今日智卷系统中有 {data['cards']['review_count']} 道错题需要复习。"
        return "无法获取复习数据。"
    except Exception as e:
        return f"连接智卷失败：{e}"


if __name__ == "__main__":
    # 1. 启动前，先确保 Flask 是活的
    ensure_flask_running()

    # 2. 启动 MCP 插件，等待 Agent 连接
    # ⚠️ 绝对不能使用 print，只能输出到 stderr
    sys.stderr.write("[MCP] 智卷 MCP 插件已启动，等待 Agent 连接...\n")
    mcp.run(transport="stdio")