# -*- coding: utf-8 -*-
"""智卷 · 一键构建脚本

用法::

    python build.py                 # 目录版（dist/智卷/）+ 便携 zip
    python build.py --onefile       # 单文件 exe（dist/智卷.exe）
    python build.py --installer     # 目录版 + Inno Setup 安装包
    python build.py --all           # 目录版 + 单文件 + 安装包
    python build.py --console       # 保留控制台窗口（排查问题用）

产物::

    dist/智卷/                            目录版，双击里面的「智卷.exe」
    dist/zhijuan-<ver>-win64-portable.zip 便携版压缩包
    dist/zhijuan-<ver>-win64-setup.exe    安装包（需要 Inno Setup）

说明：目录版启动快（无需解压），推荐作为主要发布形式；单文件版适合放 U 盘。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile

# Windows 控制台默认 GBK，遇到不可编码字符（emoji、»、—）会抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

APP_NAME = "智卷"
APP_ID = "zhijuan"
ENTRY = "run.py"


def _detect_version(default="1.0.0"):
    """版本号优先取 tag：CI 里 GITHUB_REF_NAME=v1.0.2，本地可用 ZHIJUAN_VERSION"""
    for key in ("ZHIJUAN_VERSION", "GITHUB_REF_NAME"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        v = raw[1:] if raw.startswith("v") else raw
        if re.fullmatch(r"\d+(\.\d+)*", v):
            return v
    return default


VERSION = _detect_version()
DATA_DIRS = ["templates", "static", "i18n"]
ICON_PNG = os.path.join("static", "icon-512.png")
ICON_ICO = os.path.join("static", "icon.ico")
BUILD_DIR = "build"
DIST_DIR = "dist"

HIDDEN_IMPORTS = [
    "pytesseract",
    "PIL",
    "webview",
    "webview.platforms.winforms",
    "clr",
]
EXCLUDE_MODULES = ["mcp", "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"]

ISCC_CANDIDATES = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def log(msg):
    print(f"\n=== {msg} ===")


def banner():
    """开工先亮版本号：避免把本地默认 1.0.0 的包误当成发布版"""
    print("=" * 56)
    print(f"  智卷 构建   版本 {VERSION}")
    print(f"  入口 {ENTRY}   产物目录 {DIST_DIR}/")
    if VERSION == "1.0.0" and not os.environ.get("ZHIJUAN_VERSION") \
            and not os.environ.get("GITHUB_REF_NAME"):
        print("  提示：未从 tag 取到版本号，使用默认 1.0.0")
        print("        本地想打正式版本可设 ZHIJUAN_VERSION=v1.0.2")
    print("=" * 56)


def run(cmd, **kwargs):
    print(">", " ".join(str(c) for c in cmd))
    subprocess.check_call(cmd, **kwargs)


# ---------------------------------------------------------------- 辅助产物
BRAND_COLORS = [(46, 204, 113), (52, 152, 219), (231, 76, 60), (241, 196, 15)]  # 绿/蓝/红/黄，与界面 logo 一致


def draw_logo(size=512):
    """画一枚和界面品牌一致的图标（2×2 色块）"""
    from PIL import Image, ImageDraw

    scale = size / 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1],
                        radius=int(112 * scale), fill=(255, 255, 255, 255))
    pad, gap = int(72 * scale), int(28 * scale)
    cell = (size - pad * 2 - gap) // 2
    positions = [(pad, pad),
                 (pad + cell + gap, pad),
                 (pad, pad + cell + gap),
                 (pad + cell + gap, pad + cell + gap)]
    for (x, y), color in zip(positions, BRAND_COLORS):
        d.rounded_rectangle([x, y, x + cell, y + cell],
                            radius=int(32 * scale), fill=color + (255,))
    return img


def ensure_png_icons():
    """仓库里的 PWA 图标曾经是 0 字节空文件，这里补齐"""
    from PIL import Image

    need = []
    for name, size in (("icon-512.png", 512), ("icon-192.png", 192)):
        p = os.path.join("static", name)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            need.append((p, size))
    if not need:
        return
    base = draw_logo(512)
    for p, size in need:
        img = base if size == 512 else base.resize((size, size), Image.LANCZOS)
        img.save(p)
        print(f"[OK] 生成图标 {p}")


def ensure_icon():
    """把 icon-512.png 转成多尺寸 .ico（PyInstaller 需要 .ico）"""
    if os.path.exists(ICON_ICO):
        return ICON_ICO
    try:
        ensure_png_icons()
    except Exception as e:
        print(f"[WARN] 图标生成失败：{e}")
        return None
    if not os.path.exists(ICON_PNG):
        print("[WARN] 找不到 static/icon-512.png，跳过图标")
        return None
    try:
        from PIL import Image
    except ImportError:
        print("[WARN] 没有安装 Pillow，跳过图标")
        return None
    img = Image.open(ICON_PNG).convert("RGBA")
    img.save(ICON_ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                              (64, 64), (128, 128), (256, 256)])
    print(f"[OK] 生成图标 {ICON_ICO}")
    return ICON_ICO


def write_version_info():
    """Windows 文件属性里的版本/产品名，右键 exe → 属性 可以看到"""
    os.makedirs(BUILD_DIR, exist_ok=True)
    path = os.path.join(BUILD_DIR, "version_info.txt")
    parts = [int(x) for x in VERSION.split(".")]
    while len(parts) < 4:
        parts.append(0)
    v = tuple(parts[:4])
    path = os.path.abspath(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={v}, prodvers={v},
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('CompanyName', 'Snowly17'),
        StringStruct('FileDescription', '智卷 · 本地优先的智能题库系统'),
        StringStruct('FileVersion', '{VERSION}'),
        StringStruct('InternalName', '{APP_ID}'),
        StringStruct('OriginalFilename', '{APP_NAME}.exe'),
        StringStruct('ProductName', '智卷'),
        StringStruct('ProductVersion', '{VERSION}'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""")
    return path


# ---------------------------------------------------------------- 打包
def pyinstaller_args(onefile, console):
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", APP_NAME,
        "--onefile" if onefile else "--onedir",
        "--distpath", DIST_DIR,
        "--workpath", os.path.join(BUILD_DIR, "pyinstaller"),
        "--specpath", BUILD_DIR,
    ]
    if not console:
        args.append("--windowed")
    # 注意：带 --specpath 时 PyInstaller 会把相对路径按 spec 所在目录解析，
    # 所以 --add-data / --icon 的源路径必须给绝对路径
    for d in DATA_DIRS:
        args += ["--add-data", f"{os.path.abspath(d)}{os.pathsep}{d}"]
    icon = ensure_icon()
    if icon:
        args += ["--icon", os.path.abspath(icon)]
    args += ["--version-file", write_version_info()]
    for h in HIDDEN_IMPORTS:
        args += ["--hidden-import", h]
    for m in EXCLUDE_MODULES:
        args += ["--exclude-module", m]
    for pkg in ("webview", "pythonnet", "clr_loader"):
        args += ["--collect-all", pkg]
    args.append(ENTRY)
    return args


def build(onefile=False, console=False):
    log(f"打包{'单文件' if onefile else '目录'}版（{'显示控制台' if console else '无控制台'}）")
    run(pyinstaller_args(onefile, console))

    if onefile:
        # GitHub Release 对中文文件名不友好（会被重命名成 default.exe），
        # 所以单文件产物统一再复制一份 ASCII 名字用于发布
        src = os.path.join(DIST_DIR, f"{APP_NAME}.exe")
        dst = os.path.join(DIST_DIR, f"{APP_ID}-{VERSION}-win64-single.exe")
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"[OK] 单文件版：{dst}（{os.path.getsize(dst) / 1024 / 1024:.1f} MB）")


TEST_ARTIFACTS = ("data", "app.log", "crash.log", "selftest.txt", "window")


def clean_output():
    """产物目录里绝不能带测试残留（data/、app.log、selftest.txt …）。

    上次就是 dist 里留了一个 data/，用户双击后程序把它当数据目录，
    结果数据库打不开、Edge 也建不了 profile —— 这类"打包环境污染"必须清掉。
    """
    base = os.path.join(DIST_DIR, APP_NAME)
    if not os.path.isdir(base):
        return
    for name in TEST_ARTIFACTS:
        p = os.path.join(base, name)
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
                print(f"[OK] 清理测试残留目录 {p}")
            elif os.path.exists(p):
                os.remove(p)
                print(f"[OK] 清理测试残留文件 {p}")
        except Exception as e:
            print(f"[WARN] 清理 {p} 失败：{e}")


def make_zip():
    """把目录版压成便携包"""
    src = os.path.join(DIST_DIR, APP_NAME)
    if not os.path.isdir(src):
        print("[WARN] 没有目录版产物，跳过 zip")
        return None
    name = f"{APP_ID}-{VERSION}-win64-portable.zip"
    out = os.path.join(DIST_DIR, name)
    if os.path.exists(out):
        os.remove(out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for base, _, files in os.walk(src):
            for fn in files:
                full = os.path.join(base, fn)
                z.write(full, os.path.relpath(full, src))
    mb = os.path.getsize(out) / 1024 / 1024
    print(f"[OK] 便携包：{out}（{mb:.1f} MB）")
    return out


def find_iscc():
    for p in ISCC_CANDIDATES:
        if os.path.exists(p):
            return p
    found = shutil.which("ISCC")
    return found


def build_installer():
    iscc = find_iscc()
    if not iscc:
        print("[WARN] 没找到 Inno Setup（ISCC.exe），跳过安装包")
        print("       安装：winget install JRSoftware.InnoSetup")
        print("       然后重跑：python build.py --installer")
        return None
    if not os.path.isdir(os.path.join(DIST_DIR, APP_NAME)):
        print("[WARN] 需要先构建目录版，跳过安装包")
        return None
    log("生成安装包")
    run([iscc, f"/DMyAppVersion={VERSION}", "installer.iss"])
    out = os.path.join(DIST_DIR, "installer",
                       f"{APP_ID}-{VERSION}-win64-setup.exe")
    if os.path.exists(out):
        mb = os.path.getsize(out) / 1024 / 1024
        print(f"[OK] 安装包：{out}（{mb:.1f} MB）")
        return out
    return None


def report():
    log("产物")
    if not os.path.isdir(DIST_DIR):
        print("（无）")
        return
    for name in sorted(os.listdir(DIST_DIR)):
        p = os.path.join(DIST_DIR, name)
        if os.path.isdir(p):
            print(f"  [目录] {name}/")
        else:
            print(f"  {name:44s} {os.path.getsize(p) / 1024 / 1024:7.1f} MB")


def main():
    ap = argparse.ArgumentParser(description="智卷打包脚本")
    ap.add_argument("--onefile", action="store_true", help="构建单文件 exe")
    ap.add_argument("--installer", action="store_true", help="构建 Inno Setup 安装包")
    ap.add_argument("--all", action="store_true", help="目录版 + 单文件 + 安装包")
    ap.add_argument("--console", action="store_true", help="保留控制台窗口")
    ap.add_argument("--no-zip", action="store_true", help="不生成便携 zip")
    args = ap.parse_args()

    if not args.onefile and not args.installer and not args.all:
        args.all = False  # 默认：目录版 + zip

    banner()

    built_dir = False
    if not args.onefile or args.all:
        build(onefile=False, console=args.console)
        built_dir = True

    if args.onefile or args.all:
        build(onefile=True, console=args.console)

    if built_dir and not args.no_zip:
        clean_output()
        make_zip()

    if args.installer or args.all:
        build_installer()

    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
