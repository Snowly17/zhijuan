# -*- coding: utf-8 -*-
"""智卷 · 桌面壳

三级降级策略，保证「双击就是一个像样的桌面窗口」：

1. **pywebview + WebView2**：真正的原生窗口（首选）
2. **浏览器 --app 窗口**：Edge/Chrome 的无地址栏窗口，独立进程、独立 profile，
   不污染用户日常浏览器；pythonnet 在打包环境里偶尔会加载失败，靠这层兜底
3. **默认浏览器**：交给 ``app.main`` 处理（返回值 "unavailable" / "degraded"）

返回值约定：
    "ok"          窗口模式正常结束（用户关窗）
    "degraded"    服务已起但窗口起不来，调用方应改用浏览器
    "unavailable" 环境完全不支持，调用方应改用浏览器
"""
import os
import subprocess
import sys
import threading
import time
import urllib.request

WINDOW_W, WINDOW_H = 1280, 860
MIN_W, MIN_H = 980, 640
STARTUP_TIMEOUT = 25.0

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _wait_until_up(url, timeout=STARTUP_TIMEOUT, interval=0.15):
    """等服务真正可访问了再开窗口，避免窗口里先闪一屏连接失败"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            time.sleep(interval)
    return False


def _find_browser():
    for path in EDGE_PATHS + CHROME_PATHS:
        if os.path.exists(path):
            return path
    return None


def _is_elevated():
    """当前进程是否以管理员权限运行"""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


PROFILE_LOCKS = ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")


def _clean_profile_locks(profile_dir):
    """清掉上次异常退出留下的 profile 锁，否则新窗口只会是空白页"""
    for name in PROFILE_LOCKS:
        try:
            os.remove(os.path.join(profile_dir, name))
        except Exception:
            pass


def _run_app_window(url, profile_dir):
    """用 Edge/Chrome 的 --app 模式开一个无地址栏窗口，返回是否成功"""
    exe = _find_browser()
    if not exe:
        return False
    try:
        os.makedirs(profile_dir, exist_ok=True)
        _clean_profile_locks(profile_dir)
        proc = subprocess.Popen([
            exe,
            f"--app={url}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            f"--window-size={WINDOW_W},{WINDOW_H}",
        ])
    except Exception as e:
        print(f"[WARN] 无法启动 {os.path.basename(exe)} 应用窗口：{e}")
        return False

    print(f"[OK] 已用 {os.path.basename(exe)} 应用窗口模式打开：{url}")
    proc.wait()          # 等用户关窗
    return True


def _prepare_pythonnet():
    """打包后 pythonnet 需要显式告诉它 python DLL 在哪，否则 netfx 加载器会报
    'Failed to resolve Python.Runtime.Loader.Initialize'。"""
    if not getattr(sys, "frozen", False):
        return
    base = getattr(sys, "_MEIPASS", "") or ""
    dll = os.path.join(base, "python%d%d.dll" % sys.version_info[:2])
    if os.path.exists(dll):
        os.environ.setdefault("PYTHONNET_PYDLL", dll)


def run_desktop(url, port, server_runner, profile_dir=None):
    # Flask 放到后台线程，主线程留给 GUI（Windows 要求 GUI 在主线程）
    threading.Thread(target=server_runner, args=(port,), daemon=True).start()

    if not _wait_until_up(url):
        print("[WARN] 本地服务启动超时，放弃窗口模式")
        return "degraded"

    try:
        _prepare_pythonnet()
        import webview
        from i18n import t

        webview.create_window(
            t("app.name"),
            url,
            width=WINDOW_W,
            height=WINDOW_H,
            min_size=(MIN_W, MIN_H),
            text_select=True,
        )
        webview.start(debug=False)   # 阻塞到窗口关闭
        return "ok"
    except Exception as e:
        print(f"[WARN] pywebview 不可用（{e}），改用浏览器应用窗口")

    if _is_elevated():
        # 管理员权限下启动浏览器，会把管理员令牌传给 msedge/chrome：
        # 用户之后再正常开浏览器就会看到"现有实例正在以提升的权限运行"。
        print("[WARN] 检测到管理员权限，跳过浏览器应用窗口（避免污染用户的浏览器进程）")
        return "elevated"

    profile = profile_dir or os.path.join(os.path.expanduser("~"), ".zhijuan-window")
    if _run_app_window(url, profile):
        return "ok"

    print("[WARN] 没有可用的桌面窗口方案，回退到默认浏览器")
    return "degraded"
