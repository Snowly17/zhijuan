# -*- coding: utf-8 -*-
"""兼容旧入口。

原来的 ``build_exe.py`` 只能打单文件 exe，现在统一由 ``build.py`` 负责：

    python build.py              # 目录版 + 便携 zip（推荐）
    python build.py --all        # 目录版 + 单文件 + 安装包

为了不让旧的习惯失效，这里原样转调 build.py。
"""
import sys

from build import main

if __name__ == "__main__":
    print("[提示] build_exe.py 已并入 build.py（默认打目录版），正在转调 …")
    sys.exit(main())
