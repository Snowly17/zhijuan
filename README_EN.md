# 智卷 · Local-first Quiz Bank System

> No upload, no sign-up, works offline — a lightweight quiz bank tool that runs entirely on your own machine.

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3+-green.svg)](https://flask.palletsprojects.com/)
[![pywebview](https://img.shields.io/badge/Desktop-pywebview%20%2B%20WebView2-orange.svg)](https://pywebview.flowrl.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[中文文档](README.md) · English

## Download

Grab the latest build from [Releases](https://github.com/Snowly17/zhijuan/releases):

| Package | Description |
| --- | --- |
| `zhijuan-*-win64-portable.zip` | Portable folder build. Unzip, run `智卷.exe`. Fastest start-up. |
| `zhijuan-*-win64-setup.exe` | Windows installer with Start-menu / desktop shortcuts. |

Windows 10/11 x64. The WebView2 runtime is required for the native window; it
ships with modern Windows and is installed by the installer if missing.

## Why ZhiJuan

Quiz apps usually keep your question bank, answers and mistake log in someone
else's cloud. ZhiJuan does the opposite: **everything lives in a local SQLite
file (`%APPDATA%\智卷\quiz.db`), keeps working with the network cable unplugged,
and is gone the moment you delete that file.**

## Features

- 📥 **Smart parsing** — import Word / PDF / JSON / CSV; detects question type,
  splits options, extracts answers (90-95% for `.docx`, 100% for structured data)
- 📝 **Paper generation** — auto-splits large banks into multiple papers
- ✍️ **Online answering** — single / multiple / true-false / blank / short answer,
  all graded automatically
- 📕 **Wrong-answer book** — grouped by paper so mistakes never mix
- 🧠 **Spaced repetition** — SM-2 scheduling tells you what to review today
- 🔒 **Local first** — no telemetry, no account, no network calls
- 🌏 **Trilingual UI** — 中文 / English / 日本語, switchable in-page
- 🖥️ **Native desktop window** — pywebview + WebView2, no Electron bloat
- 🤖 **Optional local AI** — Ollama integration for AI parsing and variant questions

## Quick start (from source)

```bash
git clone https://github.com/Snowly17/zhijuan.git
cd zhijuan

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt

python app.py                  # opens a native window
python app.py --browser        # force browser mode
```

Then visit <http://127.0.0.1:5001> (browser mode). The port auto-advances if
5001 is already taken.

## Supported input formats

### JSON (recommended)

```json
[
  {
    "type": "single",
    "question": "Which one is a Python web framework?",
    "options": ["Django", "Flask", "Java", "Spring"],
    "answer": "A",
    "score": 2
  }
]
```

Question types: `single`, `multiple`, `judge`, `blank`, `short`.

### CSV

Columns: `type,question,optionA,optionB,optionC,optionD,answer,score`

### Word / PDF

Parsed automatically after upload. Scanned PDFs need Tesseract-OCR.

## Build your own executable

```bash
pip install -r requirements-dev.txt

python build.py              # dist/智卷/ + portable zip (recommended)
python build.py --onefile    # single-file exe
python build.py --installer  # + Inno Setup installer (needs Inno Setup 6)
python build.py --all        # everything
python build.py --console    # keep the console window for debugging
```

Tagging `v1.0.0` triggers the GitHub Actions workflow, which builds the
portable zip and single-file exe and attaches them to a Release.

## Project layout

```
zhijuan/
├── app.py               # Flask app + routes + startup (desktop / browser)
├── desktop.py           # pywebview native window shell
├── parsers.py           # DOCX / PDF / OCR question parsers
├── sm2.py               # SM-2 spaced-repetition algorithm
├── build.py             # PyInstaller + Inno Setup build script
├── installer.iss        # Inno Setup definition
├── i18n/                # zh_CN / en_US / ja_JP dictionaries
├── templates/           # Jinja2 pages
├── static/              # CSS / JS / icons
├── docs/                # design & parser notes
└── tests/               # unit tests
```

## Data & privacy

All banks, papers, scores and mistake logs stay in
`%APPDATA%\智卷\quiz.db` (Windows) or `data/quiz.db` in development.
Deleting that file destroys everything. See
[docs/隐私说明.md](docs/隐私说明.md).

## License

MIT License · Copyright (c) 2026 Snowly17
