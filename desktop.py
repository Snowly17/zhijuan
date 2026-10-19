# -*- coding: utf-8 -*-
"""智卷 · 桌面壳（pywebview）

思路：窗口里装的就是本机 127.0.0.1 上的 Flask 页面，界面代码与浏览器模式完全一致，
只是外面套了一个没有地址栏的原生窗口（Windows 用 WebView2 / EdgeChromium 渲染）。

返回状态给 ``app.main``：
    "ok"          窗口模式正常退出（用户关窗）
    "degraded"    服务已起但窗口异常，调用方应改用浏览器打开
    "unavailable" 环境不支持（没装 pywebview 等），调用方应回退浏览器模式
"""
import threading
import time
import urllib.request

WINDOW_W, WINDOW_H = 1280, 860
MIN_W, MIN_H = 980, 640
STARTUP_TIMEOUT = 25.0


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


def run_desktop(url, port, server_runner):
    try:
        import webview
    except Exception as e:  # 没装 pywebview / 缺少 GUI 依赖
        print(f"[WARN] 无法加载 pywebview：{e}")
        return "unavailable"

    from i18n import t

    # Flask 放到后台线程，主线程留给 GUI（Windows 要求 GUI 在主线程）
    threading.Thread(target=server_runner, args=(port,), daemon=True).start()

    if not _wait_until_up(url):
        print("[WARN] 本地服务启动超时，放弃窗口模式")
        return "degraded"

    try:
        webview.create_window(
            t("app.name"),
            url,
            width=WINDOW_W,
            height=WINDOW_H,
            min_size=(MIN_W, MIN_H),
            text_select=True,
        )
        webview.start(debug=False)  # 阻塞到窗口关闭
        return "ok"
    except Exception as e:
        print(f"[WARN] pywebview 启动失败：{e}")
        return "degraded"
