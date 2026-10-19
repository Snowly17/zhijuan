# -*- coding: utf-8 -*-
"""智卷 · 打包入口

直接 ``python app.py`` 与打包都用同一个 ``app.main()``，区别只是这里多包了一层
异常兜底：窗口程序没有控制台，一旦启动阶段就崩，用户只会看到窗口一闪而过。
这层兜底会把 traceback 写进 crash.log 并弹一个提示框，便于反馈问题。

源码运行：``python app.py``  或  ``python run.py``
打包运行：PyInstaller 的入口用本文件（见 build.py 的 ENTRY）
"""
import os
import sys
import traceback
import datetime


def _selftest():
    """把运行环境关键信息写到 exe 同级 selftest.txt，便于远程排查"""
    out = os.path.join(os.path.dirname(sys.executable), "selftest.txt")
    lines = [
        f"frozen      : {getattr(sys, 'frozen', False)}",
        f"executable  : {sys.executable}",
        f"cwd         : {os.getcwd()}",
        f"APPDATA     : {os.environ.get('APPDATA')}",
        f"TEMP        : {os.environ.get('TEMP')}",
        f"python      : {sys.version.split()[0]}",
    ]
    try:
        import app as a
        lines += [
            f"LOCALAPPDATA: {os.environ.get('LOCALAPPDATA')}",
            f"data_dir    : {a.get_data_dir()}",
            f"DB_PATH     : {a.DB_PATH}",
            f"db_exists   : {os.path.exists(a.DB_PATH)}",
            f"templates   : {a.get_resource_path('templates')} (dir={os.path.isdir(a.get_resource_path('templates'))})",
            f"i18n        : {a.get_resource_path('i18n')} (dir={os.path.isdir(a.get_resource_path('i18n'))})",
            f"static      : {a.get_resource_path('static')} (dir={os.path.isdir(a.get_resource_path('static'))})",
            "",
            _env_report(),
        ]
        try:
            a.init_db()
            lines.append("init_db     : OK")
        except Exception:
            lines.append("init_db     : FAIL\n" + traceback.format_exc())
        try:
            import webview
            lines.append(f"pywebview   : {getattr(webview, '__version__', 'imported')}")
        except Exception as e:
            lines.append(f"pywebview   : import failed ({e})")
    except Exception:
        lines.append("app import failed:\n" + traceback.format_exc())

    text = "\n".join(lines) + "\n"
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        out = os.path.join(os.environ.get("TEMP") or ".", "zhijuan-selftest.txt")
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text)
    print("written to:", out)
    return 0


def _probe(path):
    """在指定目录里真的跑一遍「建 → 写 → 删」，返回 (是否可写, 错误说明)"""
    probe = os.path.join(path, ".write-test")
    try:
        os.makedirs(path, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write("1")
        os.remove(probe)
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _is_admin():
    try:
        import ctypes
        return "是（管理员）" if ctypes.windll.shell32.IsUserAnAdmin() else "否"
    except Exception:
        return "?"


def _env_report():
    """出一份能直接判断「为什么写不进去」的环境快照"""
    lines = [
        "应用程序 : " + (sys.executable or "?"),
        "启动目录 : " + os.getcwd(),
        "打包模式 : " + str(getattr(sys, "frozen", False)),
        "运行用户 : " + (os.environ.get("USERNAME") or "?"),
        "是否提权 : " + _is_admin(),
        "",
        "候选数据目录（探针：建→写→删）：",
    ]
    try:
        from app import data_dir_candidates
        candidates = data_dir_candidates()
    except Exception as e:
        candidates = []
        lines.append(f"  （读取候选目录失败：{e}）")

    for c in candidates:
        ok, why = _probe(c)
        lines.append(f"  [{'可写' if ok else '不可写'}] {c}" + ("" if ok else f"   ({why})"))
    return "\n".join(lines)


def _crash_dump(tb):
    """把 traceback + 环境快照写到能找到的地方，Windows 下再弹个框"""
    report = tb + "\n\n---- 环境 ----\n" + _env_report()

    try:
        from app import LOG_TRIED, LOG_PATH
        if LOG_TRIED:
            report += "\n\n---- 日志候选失败原因 ----\n" + "\n".join(LOG_TRIED)
        if LOG_PATH:
            report += f"\n\n（主日志：{LOG_PATH}）"
    except Exception:
        pass

    paths = []
    try:
        from app import get_data_dir
        paths.append(os.path.join(get_data_dir(), "crash.log"))
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        try:
            paths.append(os.path.join(os.path.dirname(sys.executable), "crash.log"))
        except Exception:
            pass
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    paths.append(os.path.join(temp, "zhijuan-crash.log"))

    header = f"\n{'=' * 50}\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] 启动失败\n"
    written = None
    for p in paths:
        try:
            with open(p, "a", encoding="utf-8", errors="replace") as f:
                f.write(header + report + "\n")
            written = p
            break
        except Exception:
            continue

    try:
        import ctypes
        tail = tb.strip().splitlines()[-1] if tb.strip() else "未知错误"
        ctypes.windll.user32.MessageBoxW(
            0,
            f"{tail}\n\n{_env_report()}\n\n完整日志：{written or '（三处都写不进去）'}",
            "智卷启动失败",
            0x10,
        )
    except Exception:
        pass
    sys.stderr.write(report)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        from app import main

        exit_code = main()
    except SystemExit:
        raise
    except BaseException:
        _crash_dump(traceback.format_exc())
        exit_code = 1
    sys.exit(exit_code)
