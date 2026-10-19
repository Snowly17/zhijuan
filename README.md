# 智卷 · 本地优先的智能题库系统

> 数据不上传、不注册、断网可用的轻量级题库工具

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3+-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Desktop](https://img.shields.io/badge/Desktop-pywebview%20%2B%20WebView2-orange.svg)](https://pywebview.flowrl.com/)

[English](README_EN.md) · 中文

## 下载即用（Windows 10/11 x64）

到 [Releases](https://github.com/Snowly17/zhijuan/releases) 下载最新版，两种任选：

| 包 | 说明 |
| --- | --- |
| `zhijuan-<版本>-win64-portable.zip` | 便携版：解压后双击 `智卷.exe`，启动最快（无需安装） |
| `zhijuan-<版本>-win64-setup.exe` | 安装版：装完有开始菜单与桌面快捷方式 |

双击后弹出的是一个**独立窗口**（不是浏览器标签页），关掉窗口即退出。
数据存在 `%APPDATA%\智卷\quiz.db`，卸载重装不会丢题库。

窗口按三级降级，哪一级能跑用哪一级，不会因为缺组件就打不开：

1. **pywebview + WebView2**：真·原生窗口（首选）
2. **Edge / Chrome 应用窗口**：无地址栏的独立窗口，使用专用 profile，不影响日常浏览器
3. **系统默认浏览器**：兜底

> 数据目录如果不可写（例如放在只读 U 盘），会自动退到 exe 同级的 `data/`。
> 需要排查环境时运行 `智卷.exe --selftest`，会在 exe 同级生成 `selftest.txt`。

## 为什么是智卷

市面题库 App 都在云端，你的题库、答题记录、错题本全在厂商服务器。智卷不一样：**所有数据存在你电脑的 SQLite 文件里，断网也能用，删除即销毁。**

## 核心特性

- 📥 **智能解析**：上传 Word / PDF / JSON / CSV，自动识别题型、拆分选项、提取答案
- 📝 **自动出卷**：题多自动拆分成多张卷子
- ✍️ **在线答题**：单选、多选、判断、填空、简答，五种题型自动批分
- 📕 **错题本**：按试卷名分组，不混在一起
- 🧠 **遗忘曲线复习**：基于 SM-2 算法，每天自动安排该复习的错题
- 🔒 **私有化**：数据全在本地，不联网、不收集、不上传
- 🌏 **多语言**：中文 / English / 日本語

## 从源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/Snowly17/zhijuan.git
cd zhijuan

# 2. 建虚拟环境并安装依赖
python -m venv venv
venv\Scripts\activate            # Windows；macOS/Linux 用 source venv/bin/activate
pip install -r requirements.txt

# 3. 启动（首次运行自动在 data/ 下建库建表）
python app.py                    # 默认开窗口
python app.py --browser          # 强制用浏览器打开（调试或窗口不可用时）
python run.py --selftest         # 环境自检：打印数据目录/依赖/窗口内核
```

窗口模式下不需要记端口；浏览器模式下访问 <http://127.0.0.1:5001>，
5001 被占用时会自动顺延。

> **升级提示（仅旧版本需要）**：全新 clone 不需要任何额外初始化——首次启动会自动建好含遗忘曲线字段的完整表结构。只有从旧版本升级、`data/quiz.db` 已存在却缺少 `ease` / `interval_days` / `repetitions` / `next_review` 字段时，才需要在项目根目录跑一次 `python migrate.py` 补这 4 列（它就地修改 `data/quiz.db`，所以该文件必须先存在）。

## 使用说明

1. **上传题库**：点击首页"上传题库"，选择 `.json` 或 `.csv` 文件
2. **生成试卷**：设置每张卷子题数，点"生成试卷"
3. **开始答题**：点试卷列表里的"开始答题"
4. **查看错题**：进"错题本"看所有错题，按卷名分组
5. **每日复习**：点"今日复习"，按遗忘曲线安排的错题会依次出现

## 支持的题库格式

### JSON（推荐）

```json
[
  {
    "type": "single",
    "question": "以下哪个是 Python 的 Web 框架？",
    "options": ["Django", "Flask", "Java", "Spring"],
    "answer": "A",
    "score": 2
  }
]
```

支持的题型：`single`（单选）、`multiple`（多选）、`judge`（判断）、`blank`（填空）、`short`（简答）。

### CSV

列名：`type,question,optionA,optionB,optionC,optionD,answer,score`

### Word / PDF

上传后系统自动解析。详细格式要求见 [docs/解析器工作原理.md](docs/解析器工作原理.md)。

> **通过率预期**：
> - `.docx`：90%—95%
> - `.json` / `.csv`：100%
> - `.pdf`（可编辑）：70%—85%
> - `.pdf`（扫描件）：50%—70%（需安装 Tesseract-OCR）
>
> 图片题、OCR 错字题无法自动解析，需在预览页手工补录。

## 断网演示

拔掉网线，系统所有功能正常运行。所有数据在 `data/quiz.db`（开发环境）或 `%APPDATA%\智卷\quiz.db`（打包后）。

## 隐私承诺

详见 [docs/隐私说明.md](docs/隐私说明.md)

一句话概括：**数据不上传、不收集、不共享，删除 `quiz.db` 即彻底销毁。**

## 项目结构

```
zhijuan/
├── app.py                 # Flask 主程序 + 启动入口（原生窗口/浏览器）
├── run.py                 # 打包入口（加崩溃兜底与 --selftest 自检）
├── desktop.py             # 桌面壳：pywebview → Edge 应用窗口 → 浏览器，三级降级
├── parsers.py             # 题库文件解析器
├── sm2.py                 # SM-2 遗忘曲线算法
├── migrate.py             # 数据库迁移脚本（旧版本才会用到）
├── build.py               # 打包脚本（PyInstaller + Inno Setup）
├── build_exe.py           # 旧入口，已转调 build.py
├── installer.iss          # Inno Setup 安装包定义
├── requirements.txt       # 运行时依赖
├── requirements-dev.txt   # 打包 + 测试依赖
├── i18n/                  # 多语言资源
│   ├── __init__.py
│   ├── zh_CN.json
│   ├── en_US.json
│   └── ja_JP.json
├── templates/             # Jinja2 模板
├── static/                # CSS / JS / 图标
├── .github/workflows/     # CI：打 tag 自动构建并发布
├── data/                  # SQLite 数据库（自动生成，不入库）
├── docs/                  # 文档
├── tests/                 # 单元测试
└── screenshots/           # 截图
```

## 开发

```bash
# 安装打包 + 测试依赖（普通用户只需要 requirements.txt）
pip install -r requirements-dev.txt

# 运行单元测试
pytest tests/

# 强制启用 OCR（PDF 图片型）
# 在 /convert 页面勾选「强制启用 OCR」
```

## 打包与发布

```bash
python build.py              # 目录版 dist/智卷/ + 便携 zip（推荐，启动最快）
python build.py --onefile    # 单文件 exe（便携，但每次启动要解压，较慢）
python build.py --installer  # 目录版 + Inno Setup 安装包（需先装 Inno Setup 6）
python build.py --all        # 全部产物
python build.py --console    # 保留控制台窗口，排查问题时用
```

- 图标：`build.py` 会自动把 `static/icon-512.png` 转成多尺寸 `static/icon.ico`
- 版本号：写在 `build.py` 顶部 `VERSION`，同时写进 exe 的文件属性
- 安装包：`winget install JRSoftware.InnoSetup` 后重跑 `--installer`
- CI：推 `v1.0.0` 这样的 tag，GitHub Actions 会自动构建并生成 Release 附件

### 依赖说明

- `Flask`：Web 框架
- `pywebview`：桌面原生窗口（内部用系统 WebView2 渲染，不需要 Electron）
- `python-docx`：解析 Word 题库
- `pdfplumber`：解析 PDF 题库
- `PyMuPDF` / `PyPDF2`：PDF 文本提取的加速与兜底方案
- `pytesseract` + `Pillow`：OCR（可选，PDF 图片型才需要）
- `pytest` / `pyinstaller`：测试与打包（在 `requirements-dev.txt` 里）

## 贡献

欢迎提交 Issue 和 PR。提交前请确保 `pytest tests/` 全绿。

## 截图

> 截图待补，请查看 [screenshots/](screenshots/) 目录。

<!-- 截图补齐后取消注释：
| 首页 | 答题页 |
| --- | --- |
| ![首页](screenshots/01_home.png) | ![答题页](screenshots/02_exam.png) |

| 错题本 | 遗忘曲线复习 |
| --- | --- |
| ![错题本](screenshots/03_wrong_book.png) | ![遗忘曲线复习](screenshots/04_review.png) |
-->

## License

MIT License

Copyright (c) 2026 [Snowly17]

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


