# -*- coding: utf-8 -*-
"""
智卷 · 本地优先的智能题库系统
- 支持上传 JSON/CSV/docx/pdf 题库
- 自动出卷、在线答题、自动批分
- 错题本按卷名分组
- SM-2 遗忘曲线复习
- 多语言（中文/English/日本語）
- 数据全在本地，断网可用
"""
import os
import sys
import io
import csv
import json
import re
import uuid
import time
import sqlite3
import random
import threading
import webbrowser
import datetime
import requests
from datetime import date

from flask import (
    Flask, request, jsonify, render_template, g,
    session, redirect, url_for, Response, send_file,  # 补上 send_file
)
# 补充 Word 生成依赖
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

import parsers
import i18n
from i18n import t
from sm2 import update_sm2, get_today_review

# 控制台编码兜底：Windows 控制台默认 GBK，print 里带 emoji/日文会直接抛
# UnicodeEncodeError 把程序搞崩，这里统一降级成 '?' 而不是报错。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


# ==================== 路径处理（兼容 PyInstaller 打包） ====================
def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_data_dir():
    try:
        if sys.platform == "win32":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
            data_dir = os.path.join(base, "智卷")
        elif sys.platform == "darwin":
            data_dir = os.path.expanduser("~/Library/Application Support/智卷")
        else:
            data_dir = os.path.expanduser("~/.local/share/智卷")
        os.makedirs(data_dir, exist_ok=True)
        return data_dir
    except Exception as e:
        # 👇 兜底：如果用户目录不可写，退回到 exe 所在的当前目录
        print(f"[WARN] 无法创建系统数据目录，回退到当前目录：{e}")
        fallback_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(fallback_dir, exist_ok=True)
        return fallback_dir


if getattr(sys, "frozen", False):
    DB_PATH = os.path.join(get_data_dir(), "quiz.db")
else:
    _dev_data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(_dev_data, exist_ok=True)
    DB_PATH = os.path.join(_dev_data, "quiz.db")

# ==================== Flask 初始化 ====================
app = Flask(
    __name__,
    template_folder=get_resource_path("templates"),
    static_folder=get_resource_path("static"),
)
# 优先读取环境变量，如果没有则每次启动随机生成（更安全）
app.secret_key = os.environ.get("SECRET_KEY", uuid.uuid4().hex)
i18n.register(app)

# ==================== 常量 ====================

# 解析结果缓存（进程内）
PARSE_CACHE = {}
PARSE_CACHE_TTL = 1800  # 30 分钟

# 👇 新增：题库市场配置（替换为你自己的 GitHub raw 链接）
MARKET_CATALOG_URL = "https://raw.githubusercontent.com/Snowly17/zhijuan-banks/main/catalog.json"


# ==================== 数据库 ====================
def get_db():
    if "db" not in g:
        # 👇 核心修复：加入 timeout=20，让线程排队等待，而不是直接报错
        g.db = sqlite3.connect(DB_PATH, timeout=20)
        g.db.row_factory = sqlite3.Row
        # 开启 WAL 模式，允许读写并发
        g.db.execute("PRAGMA journal_mode=WAL;")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        question TEXT NOT NULL,
        options TEXT DEFAULT '[]',
        answer TEXT NOT NULL,
        score REAL DEFAULT 2,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS papers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        question_ids TEXT NOT NULL,
        total_score REAL NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_id INTEGER NOT NULL,
        paper_name TEXT NOT NULL,
        score REAL NOT NULL,
        total_score REAL NOT NULL,
        detail TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS wrong_book (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paper_name TEXT NOT NULL,
        question_id INTEGER NOT NULL,
        user_answer TEXT,
        correct_answer TEXT,
        question_snapshot TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        ease REAL DEFAULT 2.5,
        interval_days INTEGER DEFAULT 1,
        repetitions INTEGER DEFAULT 0,
        next_review TEXT
    );
    """)

    # 自动迁移：为旧数据库补 SM-2 字段
    _auto_migrate(conn)

    conn.commit()
    conn.close()


def _auto_migrate(conn):
    """检测旧数据库，自动补齐缺失字段"""
    try:
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(wrong_book)"
        ).fetchall()}
    except sqlite3.OperationalError:
        return

    migrations = [
        ("ease", "ALTER TABLE wrong_book ADD COLUMN ease REAL DEFAULT 2.5"),
        ("interval_days", "ALTER TABLE wrong_book ADD COLUMN interval_days INTEGER DEFAULT 1"),
        ("repetitions", "ALTER TABLE wrong_book ADD COLUMN repetitions INTEGER DEFAULT 0"),
        ("next_review", "ALTER TABLE wrong_book ADD COLUMN next_review TEXT"),
    ]

    for col, sql in migrations:
        if col not in cols:
            try:
                conn.execute(sql)
                print(f"[迁移] wrong_book 添加字段：{col}")
            except sqlite3.OperationalError as e:
                print(f"[迁移] {col} 跳过：{e}")


# ==================== 文件解析工具 ====================
def read_upload(file_storage):
    raw = file_storage.read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb2312"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def normalize_question(item):
    if not isinstance(item, dict):
        return None
    qtype = str(item.get("type", "single")).strip().lower()
    question = str(item.get("question", "")).strip()
    if not question:
        return None

    raw = item.get("answer")
    if raw is None or raw == "":
        return None

    opts = item.get("options") or []
    if isinstance(opts, str):
        opts = [o.strip() for o in opts.split("|") if o.strip()]

    # 清理选项前缀 (防止出现 A. A. xxx 的情况)
    import re
    clean_opts = []
    for o in opts:
        o = str(o).strip()
        if not o:
            continue
        o = re.sub(r'^[A-H]\s*[.、\．\)）]\s*', '', o)
        clean_opts.append(o)
    opts = clean_opts

    if qtype == "multiple":
        if isinstance(raw, str):
            answer = [a.strip().upper() for a in raw.replace("，", ",").split(",") if a.strip()]
        else:
            answer = [str(a).strip().upper() for a in raw if str(a).strip()]
    elif qtype == "single":
        answer = str(raw).strip().upper()
    elif qtype == "judge":
        a = str(raw).strip().upper()
        if a in ("T", "TRUE", "对", "正确", "√", "是", "Y"):
            answer = "T"
        elif a in ("F", "FALSE", "错", "错误", "×", "否", "N"):
            answer = "F"
        else:
            answer = a
    elif qtype in ("blank", "short"):
        if isinstance(raw, str):
            answer = [a.strip() for a in raw.split("|") if a.strip()]
        else:
            answer = [str(a).strip() for a in raw if str(a).strip()]
        if not answer:
            return None
    else:
        return None

    try:
        score = float(item.get("score", 2) or 2)
    except (TypeError, ValueError):
        score = 2

    return {
        "type": qtype,
        "question": question,
        "options": opts,
        "answer": answer,
        "score": score,
    }


def parse_json(text):
    data = json.loads(text)
    if isinstance(data, dict) and "questions" in data:
        data = data["questions"]
    if not isinstance(data, list):
        raise ValueError(t('error.json_array_required'))
    return [q for q in (normalize_question(i) for i in data) if q]


def parse_csv(text):
    alias = {
        "type": "type", "类型": "type", "题型": "type",
        "question": "question", "题目": "question", "题干": "question",
        "optiona": "optionA", "选项a": "optionA", "a": "optionA",
        "optionb": "optionB", "选项b": "optionB", "b": "optionB",
        "optionc": "optionC", "选项c": "optionC", "c": "optionC",
        "optiond": "optionD", "选项d": "optionD", "d": "optionD",
        "answer": "answer", "答案": "answer",
        "score": "score", "分值": "score", "分数": "score",
    }
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    field_map = {}
    for f in reader.fieldnames:
        key = str(f).strip().lower().replace(" ", "")
        if key in alias:
            field_map[f] = alias[key]

    out = []
    for row in reader:
        norm = {std: row.get(orig, "") for orig, std in field_map.items()}
        qtype = str(norm.get("type", "")).strip().lower()
        question = str(norm.get("question", "")).strip()
        if not question:
            continue

        opts = []
        for k in ("optionA", "optionB", "optionC", "optionD"):
            v = str(norm.get(k, "")).strip()
            if v:
                opts.append(v)

        raw = str(norm.get("answer", "")).strip()
        item = {
            "type": qtype,
            "question": question,
            "options": opts,
            "answer": raw,
            "score": norm.get("score") or 2,
        }
        q = normalize_question(item)
        if q:
            out.append(q)
    return out


# ==================== 批分 ====================
def grade_one(q, ua):
    t = q["type"]
    correct = q["answer"]
    if t == "single":
        return str(ua or "").strip().upper() == str(correct).upper()
    if t == "multiple":
        ua_list = ua if isinstance(ua, list) else []
        return sorted(str(a).upper() for a in ua_list) == \
            sorted(str(a).upper() for a in correct)
    if t == "judge":
        return str(ua or "").strip().upper() == str(correct).upper()
    if t == "blank":
        s = str(ua or "").strip().lower()
        if not s:
            return False
        return any(s == str(a).strip().lower() for a in correct)
    if t == "short":
        s = str(ua or "").strip()
        if not s:
            return False
        return any(str(kw) in s for kw in correct)
    return False


def fmt_answer(ans, qtype):
    if ans is None or ans == "" or ans == []:
        return t('common.not_answered')
    if qtype == "judge":
        return {"T": t('exam.judge_t'), "F": t('exam.judge_f')}.get(str(ans).upper(), str(ans))
    if qtype in ("multiple", "blank", "short"):
        if isinstance(ans, list):
            return " / ".join(str(a) for a in ans) or t('common.not_answered')
        return str(ans)
    return str(ans)


# ==================== 页面路由 ====================
@app.route("/")
def index():
    db = get_db()
    raw_papers = db.execute(
        "SELECT * FROM papers ORDER BY created_at DESC, id DESC"
    ).fetchall()
    papers = []
    for p in raw_papers:
        d = dict(p)
        try:
            d["qcount"] = len(json.loads(p["question_ids"]))
        except Exception:
            d["qcount"] = 0
        papers.append(d)

    qcount = db.execute("SELECT COUNT(*) c FROM questions").fetchone()["c"]
    wrong_count = db.execute("SELECT COUNT(*) c FROM wrong_book").fetchone()["c"]

    # 今日待复习数
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    review_count = db.execute(
        "SELECT COUNT(*) c FROM wrong_book "
        "WHERE next_review IS NULL OR next_review <= ?",
        (today,)
    ).fetchone()["c"]

    return render_template(
        "index.html",
        papers=papers,
        qcount=qcount,
        wrong_count=wrong_count,
        review_count=review_count,
    )


@app.route("/paper/<int:pid>")
def paper_page(pid):
    db = get_db()
    paper = db.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
    if not paper:
        return t('error.paper_not_exist'), 404
    return render_template("exam.html", paper=paper)


@app.route("/paper/<int:pid>/result/<int:rid>")
def result_page(pid, rid):
    db = get_db()
    paper = db.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
    row = db.execute("SELECT * FROM results WHERE id=?", (rid,)).fetchone()
    if not paper or not row:
        return redirect(url_for("index"))

    detail = json.loads(row["detail"])
    for d in detail:
        d["correct_display"] = fmt_answer(d["correct_answer"], d["type"])
        d["user_display"] = fmt_answer(d["user_answer"], d["type"])
    return render_template("result.html", paper=paper, result=row, detail=detail)


@app.route("/wrong")
def wrong_page():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM wrong_book ORDER BY paper_name, id"
    ).fetchall()
    groups = {}
    for r in rows:
        snap = json.loads(r["question_snapshot"] or "{}")
        correct = json.loads(r["correct_answer"] or "null")
        user_ans = json.loads(r["user_answer"] or "null")
        item = {
            "id": r["id"],
            "question": snap.get("question", ""),
            "options": snap.get("options", []),
            "type": snap.get("type", ""),
            "correct_display": fmt_answer(correct, snap.get("type", "")),
            "user_display": fmt_answer(user_ans, snap.get("type", "")),
            "created_at": r["created_at"],
        }
        groups.setdefault(r["paper_name"], []).append(item)

    paper_stats = [
        {"name": name, "count": len(items)} for name, items in groups.items()
    ]
    total_wrong = sum(g["count"] for g in paper_stats)

    return render_template(
        "wrong.html",
        groups=groups,
        paper_stats=paper_stats,
        total_wrong=total_wrong,
    )


@app.route("/review")
def review_page():
    db = get_db()
    rows = get_today_review(db)
    items = []
    for r in rows:
        snap = json.loads(r["question_snapshot"] or "{}")
        correct = json.loads(r["correct_answer"] or "null")
        items.append({
            "id": r["id"],
            "question": snap.get("question", ""),
            "options": snap.get("options", []),
            "type": snap.get("type", ""),
            "correct_display": fmt_answer(correct, snap.get("type", "")),
        })
    return render_template("review.html", items=items)


@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")


@app.route("/convert")
def convert_page():
    return render_template("convert.html")


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


# 👇 新增：题库市场页面路由
@app.route("/market")
def market_page():
    return render_template("market.html")


@app.route("/manifest.json")
def pwa_manifest():
    """PWA 清单随语言变化，不能放在 /static 里写死"""
    resp = Response(render_template("manifest.json"), mimetype="application/manifest+json")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# ==================== 上传 / 生成 / 答题 / 批分 ====================
@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "msg": t('error.select_file')}), 400
    fname = f.filename.lower()
    if not (fname.endswith(".json") or fname.endswith(".csv")):
        return jsonify({"ok": False, "msg": t('error.only_json_csv')}), 400

    try:
        text = read_upload(f)
    except Exception as e:
        return jsonify({"ok": False, "msg": t('error.read_fail').replace('{msg}', str(e))}), 400

    try:
        questions = parse_json(text) if fname.endswith(".json") else parse_csv(text)
    except Exception as e:
        return jsonify({"ok": False, "msg": t('error.parse_fail').replace('{msg}', str(e))}), 400

    if not questions:
        return jsonify({"ok": False, "msg": t('error.no_valid_questions')}), 400

    db = get_db()
    if request.form.get("replace") == "1":
        db.execute("DELETE FROM questions")

    for q in questions:
        db.execute(
            "INSERT INTO questions (type, question, options, answer, score) "
            "VALUES (?,?,?,?,?)",
            (q["type"], q["question"],
             json.dumps(q["options"], ensure_ascii=False),
             json.dumps(q["answer"], ensure_ascii=False),
             q["score"])
        )
    db.commit()
    return jsonify({"ok": True, "count": len(questions)})


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(silent=True) or {}
    try:
        per_paper = int(data.get("per_paper", 20))
    except (TypeError, ValueError):
        per_paper = 20
    per_paper = max(1, min(per_paper, 200))

    default_name = t('home.default_paper_name')
    base = (data.get("name") or default_name).strip()[:20] or default_name

    db = get_db()
    ids = [r["id"] for r in db.execute("SELECT id FROM questions").fetchall()]
    if not ids:
        return jsonify({"ok": False, "msg": t('error.empty_bank')}), 400

    random.shuffle(ids)
    chunks = [ids[i:i + per_paper] for i in range(0, len(ids), per_paper)]

    paper_ids = []
    for idx, chunk in enumerate(chunks, 1):
        vol_name = t('common.volume_n').replace('{n}', str(idx))
        name = f"{base}-{vol_name}"
        ph = ",".join("?" * len(chunk))
        srow = db.execute(
            f"SELECT COALESCE(SUM(score),0) s FROM questions WHERE id IN ({ph})",
            chunk
        ).fetchone()
        cur = db.execute(
            "INSERT INTO papers (name, question_ids, total_score) VALUES (?,?,?)",
            (name, json.dumps(chunk), round(srow["s"] or 0, 2))
        )
        paper_ids.append(cur.lastrowid)
    db.commit()
    return jsonify({"ok": True, "count": len(paper_ids), "paper_ids": paper_ids})


@app.route("/api/papers/delete_batch", methods=["POST"])
def api_papers_delete_batch():
    data = request.get_json(silent=True) or {}
    pids = data.get("pids", [])

    try:
        pids = [int(pid) for pid in pids]
    except ValueError:
        return jsonify({"ok": False, "msg": t('error.invalid_ids')}), 400

    if not pids:
        return jsonify({"ok": False, "msg": t('error.no_papers_selected')}), 400

    db = get_db()
    ph = ",".join("?" * len(pids))
    db.execute(f"DELETE FROM papers WHERE id IN ({ph})", pids)
    db.commit()
    return jsonify({"ok": True, "count": len(pids)})


@app.route("/api/paper/<int:pid>")
def api_paper(pid):
    db = get_db()
    paper = db.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
    if not paper:
        return jsonify({"ok": False, "msg": t('error.paper_not_exist')}), 404
    qids = json.loads(paper["question_ids"])
    if not qids:
        return jsonify({"ok": True, "questions": [], "name": paper["name"]})

    ph = ",".join("?" * len(qids))
    rows = db.execute(f"SELECT * FROM questions WHERE id IN ({ph})", qids).fetchall()
    qmap = {r["id"]: dict(r) for r in rows}
    out = []
    for qid in qids:
        r = qmap.get(qid)
        if not r:
            continue
        out.append({
            "id": r["id"],
            "type": r["type"],
            "question": r["question"],
            "options": json.loads(r["options"]),
            "score": r["score"],
        })
    return jsonify({"ok": True, "questions": out, "name": paper["name"]})


@app.route("/api/submit/<int:pid>", methods=["POST"])
def api_submit(pid):
    db = get_db()
    paper = db.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
    if not paper:
        return jsonify({"ok": False, "msg": t('error.paper_not_exist')}), 404

    body = request.get_json(silent=True) or {}
    user_answers = body.get("answers", {})
    qids = json.loads(paper["question_ids"])
    if not qids:
        return jsonify({"ok": False, "msg": t('error.paper_empty')}), 400

    ph = ",".join("?" * len(qids))
    rows = db.execute(f"SELECT * FROM questions WHERE id IN ({ph})", qids).fetchall()
    qmap = {r["id"]: dict(r) for r in rows}

    db.execute("DELETE FROM wrong_book WHERE paper_name=?", (paper["name"],))

    earned, total = 0.0, 0.0
    detail = []

    for qid in qids:
        q = qmap.get(qid)
        if not q:
            continue
        q["answer"] = json.loads(q["answer"])
        q["options"] = json.loads(q["options"])
        total += q["score"]

        ua = user_answers.get(str(qid))
        ok = grade_one(q, ua)
        if ok:
            earned += q["score"]

        detail.append({
            "qid": qid,
            "type": q["type"],
            "question": q["question"],
            "options": q["options"],
            "correct_answer": q["answer"],
            "user_answer": ua,
            "score": q["score"],
            "got": q["score"] if ok else 0,
            "ok": ok,
        })

        if not ok:
            db.execute(
                "INSERT INTO wrong_book (paper_name, question_id, "
                "user_answer, correct_answer, question_snapshot, next_review) "
                "VALUES (?,?,?,?,?, date('now'))",
                (paper["name"], qid,
                 json.dumps(ua, ensure_ascii=False),
                 json.dumps(q["answer"], ensure_ascii=False),
                 json.dumps({
                     "question": q["question"],
                     "options": q["options"],
                     "type": q["type"],
                 }, ensure_ascii=False))
            )

    earned, total = round(earned, 2), round(total, 2)
    cur = db.execute(
        "INSERT INTO results (paper_id, paper_name, score, total_score, detail) "
        "VALUES (?,?,?,?,?)",
        (pid, paper["name"], earned, total,
         json.dumps(detail, ensure_ascii=False))
    )
    db.commit()
    return jsonify({"ok": True, "result_id": cur.lastrowid})

def clean_xml_string(text):
    """清洗无法写入 Word 的特殊字符 (Emoji, 控制符等)"""
    if not text:
        return ""
    # 移除非法的 XML 控制字符，但保留换行和制表符
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', str(text))

# ==================== 错题重练 ====================

@app.route("/api/generate_variant/<int:rid>", methods=["POST"])
def api_generate_variant(rid):
    db = get_db()
    row = db.execute("SELECT question_snapshot FROM wrong_book WHERE id=?", (rid,)).fetchone()
    if not row:
        return jsonify({"ok": False, "msg": t('error.record_not_exist')}), 404

    snap = json.loads(row["question_snapshot"])
    orig_question = snap.get("question", "")

    try:
        variant_q = parsers.generate_variant_question(orig_question)
        return jsonify({"ok": True, "question": variant_q})
    except Exception as e:
        # 直接返回错误信息，前端通过拼接翻译显示
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/retry_wrong", methods=["POST"])
def api_retry_wrong():
    data = request.get_json(silent=True) or {}
    paper_filter = (data.get("paper_name") or "").strip()
    try:
        per_paper = int(data.get("per_paper", 20))
    except (TypeError, ValueError):
        per_paper = 20
    per_paper = max(1, min(per_paper, 200))

    db = get_db()
    if paper_filter:
        rows = db.execute(
            "SELECT DISTINCT question_id FROM wrong_book WHERE paper_name=?",
            (paper_filter,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT DISTINCT question_id FROM wrong_book"
        ).fetchall()

    qids = [r["question_id"] for r in rows]
    if not qids:
        return jsonify({"ok": False, "msg": t('error.wrong_book_empty')}), 400

    random.shuffle(qids)
    chunks = [qids[i:i + per_paper] for i in range(0, len(qids), per_paper)]

    default_retry = t('wrong_book.default_retry_name')
    base = f"{default_retry}-{paper_filter}" if paper_filter else default_retry
    base = base[:24]
    paper_ids = []
    for idx, chunk in enumerate(chunks, 1):
        vol_name = t('common.volume_n').replace('{n}', str(idx))
        name = f"{base}-{vol_name}"
        ph = ",".join("?" * len(chunk))
        srow = db.execute(
            f"SELECT COALESCE(SUM(score),0) s FROM questions WHERE id IN ({ph})",
            chunk
        ).fetchone()
        cur = db.execute(
            "INSERT INTO papers (name, question_ids, total_score) VALUES (?,?,?)",
            (name, json.dumps(chunk), round(srow["s"] or 0, 2))
        )
        paper_ids.append(cur.lastrowid)
    db.commit()
    return jsonify({"ok": True, "count": len(paper_ids), "paper_ids": paper_ids})


# ==================== 遗忘曲线复习 ====================
@app.route("/api/review/<int:rid>", methods=["POST"])
def api_review(rid):
    data = request.get_json(silent=True) or {}
    quality = int(data.get("quality", 3))
    quality = max(0, min(5, quality))

    db = get_db()
    row = db.execute(
        "SELECT ease, interval_days, repetitions FROM wrong_book WHERE id=?",
        (rid,)
    ).fetchone()
    if not row:
        return jsonify({"ok": False, "msg": t('error.record_not_exist')}), 404

    ease, interval, reps, next_review = update_sm2(
        row["ease"] or 2.5,
        row["interval_days"] or 1,
        row["repetitions"] or 0,
        quality,
    )

    db.execute(
        "UPDATE wrong_book SET ease=?, interval_days=?, repetitions=?, next_review=? "
        "WHERE id=?",
        (ease, interval, reps, next_review, rid)
    )
    db.commit()
    return jsonify({"ok": True, "next_review": next_review, "interval": interval})


# ==================== 格式转换 ====================
@app.route("/api/parse_file", methods=["POST"])
def api_parse_file():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "msg": t('error.select_file')}), 400

    fname = f.filename.lower()
    use_ocr = request.form.get("ocr") == "1"
    t0 = time.time()

    try:
        if fname.endswith(".docx"):
            raw_text = parsers.extract_text_from_docx(f.stream)
            questions = parsers.parse_question_text(raw_text)
            questions = parsers._merge_orphan_answers(questions)

        elif fname.endswith(".pdf"):
            raw_text = parsers.extract_text_from_pdf(f.stream)
            lines = [l for l in raw_text.split("\n") if l.strip()]

            if use_ocr or len(lines) < 50:
                print(f"[PDF] 启用 OCR（前 20 页测试）…")
                try:
                    f.stream.seek(0)
                    raw_text = parsers.extract_text_from_pdf_ocr(
                        f.stream, max_pages=20
                    )
                    print(f"[PDF] OCR 完成")
                except Exception as e:
                    print(f"[PDF] OCR 失败：{e}")
                    if not raw_text.strip():
                        return jsonify({"ok": False, "msg": t('error.scanned_pdf')}), 400

            questions = parsers.parse_question_text(raw_text)
            questions = parsers._merge_orphan_answers(questions)

        elif fname.endswith(".json"):
            raw_text = f.read().decode("utf-8", errors="ignore")
            questions = parse_json(raw_text)

        elif fname.endswith(".csv"):
            raw_text = f.read().decode("utf-8", errors="ignore")
            questions = parse_csv(raw_text)

        else:
            return jsonify({"ok": False, "msg": t('error.unsupported_type')}), 400
    except Exception as e:
        return jsonify({"ok": False, "msg": t('error.parse_fail').replace('{msg}', str(e))}), 400

    if not questions:
        return jsonify({"ok": False, "msg": t('error.no_valid_questions')}), 400

    sid = uuid.uuid4().hex
    PARSE_CACHE[sid] = {
        "questions": questions,
        "created_at": time.time(),
        "raw_text": raw_text,
    }

    now = time.time()
    for k in list(PARSE_CACHE.keys()):
        if now - PARSE_CACHE[k]["created_at"] > PARSE_CACHE_TTL:
            del PARSE_CACHE[k]

    stats = parsers.analyze_qnums(raw_text, questions)

    return jsonify({
        "ok": True,
        "sid": sid,
        "count": len(questions),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "missing": stats["missing"],
    })


@app.route("/api/parse_ai", methods=["POST"])
def api_parse_ai():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "msg": t('error.select_file')}), 400

    fname = f.filename.lower()

    try:
        if fname.endswith(".pdf"):
            raw_text = parsers.extract_text_from_pdf(f.stream)
        elif fname.endswith(".docx"):
            raw_text = parsers.extract_text_from_docx(f.stream)
        else:
            return jsonify({"ok": False, "msg": t('error.ai_pdf_word_only')}), 400
    except Exception as e:
        return jsonify({"ok": False, "msg": t('error.read_fail').replace('{msg}', str(e))}), 400

    if not raw_text.strip():
        return jsonify({"ok": False, "msg": t('error.no_text')}), 400

    try:
        # 获取当前系统语言，传给本地大模型
        current_lang = i18n.get_lang()
        raw_questions = parsers.extract_with_ai(raw_text, lang=current_lang)

        # 极其关键：让 AI 出来的数据也过一遍格式清洗
        questions = []
        for q in raw_questions:
            nq = normalize_question(q)
            if nq:
                questions.append(nq)

    except RuntimeError as e:
        return jsonify({"ok": False, "msg": str(e)}), 500
    except Exception as e:
        return jsonify({"ok": False, "msg": t('error.parse_fail').replace('{msg}', str(e))}), 500

    sid = uuid.uuid4().hex
    PARSE_CACHE[sid] = {"questions": questions, "created_at": time.time()}

    return jsonify({
        "ok": True,
        "sid": sid,
        "count": len(questions),
        "msg": t('error.success')
    })


@app.route("/api/parse_page/<sid>")
def api_parse_page(sid):
    cache = PARSE_CACHE.get(sid)
    if not cache:
        return jsonify({"ok": False, "msg": t('error.expired')}), 404

    try:
        page = int(request.args.get("page", 1))
        size = int(request.args.get("size", 50))
    except (TypeError, ValueError):
        page, size = 1, 50
    page = max(1, page)
    size = max(1, min(size, 200))

    questions = cache["questions"]
    total = len(questions)
    start = (page - 1) * size
    end = start + size

    return jsonify({
        "ok": True,
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
        "questions": questions[start:end],
        "start_index": start,
    })


@app.route("/api/parse_update/<sid>", methods=["POST"])
def api_parse_update(sid):
    cache = PARSE_CACHE.get(sid)
    if not cache:
        return jsonify({"ok": False, "msg": t('error.expired')}), 404

    data = request.get_json(silent=True) or {}
    idx = data.get("index")
    question = data.get("question")

    if not isinstance(idx, int) or not (0 <= idx < len(cache["questions"])):
        return jsonify({"ok": False, "msg": t('error.index_out_of_bounds')}), 400

    cache["questions"][idx] = question
    return jsonify({"ok": True})


@app.route("/api/parse_delete/<sid>", methods=["POST"])
def api_parse_delete(sid):
    cache = PARSE_CACHE.get(sid)
    if not cache:
        return jsonify({"ok": False, "msg": t('error.expired')}), 404

    data = request.get_json(silent=True) or {}
    idx = data.get("index")
    if not isinstance(idx, int) or not (0 <= idx < len(cache["questions"])):
        return jsonify({"ok": False, "msg": t('error.index_out_of_bounds')}), 400

    cache["questions"][idx] = None
    return jsonify({"ok": True})


@app.route("/api/import_parsed", methods=["POST"])
def api_import_parsed():
    data = request.get_json(silent=True) or {}
    sid = data.get("sid")
    replace = bool(data.get("replace"))

    cache = PARSE_CACHE.get(sid)
    if not cache:
        return jsonify({"ok": False, "msg": t('error.expired')}), 404

    questions = [q for q in cache["questions"] if q]

    db = get_db()
    if replace:
        db.execute("DELETE FROM questions")

    count = 0
    for q in questions:
        try:
            question = (q.get("question") or "").strip()
            answer = q.get("answer")
            if not question or answer is None:
                continue
            db.execute(
                "INSERT INTO questions (type, question, options, answer, score) "
                "VALUES (?,?,?,?,?)",
                (q.get("type", "single"), question,
                 json.dumps(q.get("options") or [], ensure_ascii=False),
                 json.dumps(answer, ensure_ascii=False),
                 float(q.get("score", 2) or 2))
            )
            count += 1
        except Exception as e:
            db.rollback()
            continue

    db.commit()
    del PARSE_CACHE[sid]
    return jsonify({"ok": True, "count": count})


# ==================== 仪表盘 ====================
@app.route("/api/dashboard_stats")
def api_dashboard_stats():
    db = get_db()

    total_results = db.execute("SELECT COUNT(*) c FROM results").fetchone()["c"]
    total_wrong = db.execute("SELECT COUNT(*) c FROM wrong_book").fetchone()["c"]

    avg_row = db.execute(
        "SELECT AVG(score * 100.0 / total_score) a FROM results WHERE total_score > 0"
    ).fetchone()
    avg_rate = round(avg_row["a"] or 0, 1)

    # 👇 修复时区问题
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    review_count = db.execute(
        "SELECT COUNT(*) c FROM wrong_book WHERE next_review IS NULL OR next_review <= ?",
        (today,)
    ).fetchone()["c"]

    today_dt = datetime.datetime.now().date()
    dates = [(today_dt - datetime.timedelta(days=i)).isoformat() for i in range(6, -1, -1)]

    week_rows = db.execute(
        "SELECT created_at, score FROM results WHERE date(created_at) >= date('now', '-7 days')"
    ).fetchall()

    daily_counts = {d: 0 for d in dates}
    daily_scores = {d: [] for d in dates}
    for r in week_rows:
        d = r["created_at"][:10]
        if d in daily_counts:
            daily_counts[d] += 1
            daily_scores[d].append(r["score"])

    details = db.execute("SELECT detail FROM results").fetchall()
    type_stats = {
        "single": {"total": 0, "correct": 0},
        "multiple": {"total": 0, "correct": 0},
        "judge": {"total": 0, "correct": 0},
        "blank": {"total": 0, "correct": 0},
        "short": {"total": 0, "correct": 0},
    }

    for row in details:
        try:
            items = json.loads(row["detail"])
            for item in items:
                t = item.get("type")
                if t in type_stats:
                    type_stats[t]["total"] += 1
                    if item.get("ok"):
                        type_stats[t]["correct"] += 1
        except Exception:
            pass

    type_rates = []
    for t in ["single", "multiple", "judge", "blank", "short"]:
        if type_stats[t]["total"] > 0:
            rate = round(type_stats[t]["correct"] * 100.0 / type_stats[t]["total"], 1)
        else:
            rate = 0
        type_rates.append(rate)

    return jsonify({
        "ok": True,
        "cards": {
            "total_papers": total_results,
            "avg_rate": avg_rate,
            "total_wrong": total_wrong,
            "review_count": review_count,
        },
        "trend": {
            "dates": dates,
            "counts": [daily_counts[d] for d in dates],
        },
        "types": {
            "labels": ["single", "multiple", "judge", "blank", "short"],
            "rates": type_rates,
        }
    })


# ==================== 👇 新增：题库市场接口 👇 ====================
@app.route("/api/market/list")
def api_market_list():
    """获取市场题库列表"""
    try:
        res = requests.get(MARKET_CATALOG_URL, timeout=5)
        res.raise_for_status()
        catalog = res.json()
        return jsonify({"ok": True, "data": catalog})
    except Exception as e:
        mock_data = [
            {
                "id": "mock-1",
                "name": t('market.mock_name'),
                "author": t('market.mock_author'),
                "count": 10,
                "desc": t('market.mock_desc'),
                "url": ""
            }
        ]
        return jsonify({"ok": True, "data": mock_data, "offline": True, "msg": str(e)})


@app.route("/api/market/import", methods=["POST"])
def api_market_import():
    """从市场下载并导入题库"""
    data = request.get_json(silent=True) or {}
    url = data.get("url")
    replace = bool(data.get("replace"))

    if not url:
        return jsonify({"ok": False, "msg": t('market.no_url')}), 400

    try:
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        questions = parse_json(res.text)
    except Exception as e:
        return jsonify({"ok": False, "msg": t('error.market_download_fail').replace('{msg}', str(e))}), 500

    if not questions:
        return jsonify({"ok": False, "msg": t('error.no_valid_questions')}), 400

    db = get_db()
    if replace:
        db.execute("DELETE FROM questions")

    count = 0
    for q in questions:
        try:
            db.execute(
                "INSERT INTO questions (type, question, options, answer, score) "
                "VALUES (?,?,?,?,?)",
                (q["type"], q["question"],
                 json.dumps(q["options"], ensure_ascii=False),
                 json.dumps(q["answer"], ensure_ascii=False),
                 q.get("score", 2))
            )
            count += 1
        except Exception:
            continue
    db.commit()

    return jsonify({"ok": True, "count": count})


@app.route("/api/market/export")
def api_market_export():
    """导出当前题库为 JSON (供用户分享)"""
    db = get_db()
    rows = db.execute("SELECT * FROM questions").fetchall()

    out = []
    for r in rows:
        out.append({
            "type": r["type"],
            "question": r["question"],
            "options": json.loads(r["options"]),
            "answer": json.loads(r["answer"]),
            "score": r["score"]
        })

    response = Response(
        json.dumps(out, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=zhijuan_export.json"}
    )
    return response


# ==================== 👆 题库市场接口结束 👆 ====================


# ==================== 调试 / OCR 环境检测 ====================
@app.route("/api/parse_debug", methods=["POST"])
def api_parse_debug():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "msg": t('error.select_file')}), 400

    fname = f.filename.lower()
    use_ocr = request.form.get("ocr") == "1"

    try:
        if fname.endswith(".pdf"):
            if use_ocr:
                text = parsers.extract_text_from_pdf_ocr(f.stream, max_pages=2)
            else:
                text = parsers.extract_text_from_pdf(f.stream)
        elif fname.endswith(".docx"):
            text = parsers.extract_text_from_docx(f.stream)
        else:
            return jsonify({"ok": False, "msg": t('error.only_pdf_docx')}), 400
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 400

    lines = text.split("\n")
    return jsonify({
        "ok": True,
        "total_lines": len(lines),
        "all_lines": lines,
        "first_60": lines[:60],
        "ocr": use_ocr,
    })

@app.route("/api/parse_raw/<sid>")
def api_parse_raw(sid):
    """直接从前端缓存秒拉原文，不再重新解析文件"""
    cache = PARSE_CACHE.get(sid)
    if not cache:
        return jsonify({"ok": False, "msg": t('error.expired')}), 404

    raw_text = cache.get("raw_text", "")
    lines = raw_text.split("\n")
    return jsonify({
        "ok": True,
        "total_lines": len(lines),
        "all_lines": lines,
        "first_60": lines[:60],
    })

@app.route("/api/check_env")
def api_check_env():
    result = {
        "ok": True,
        "pytesseract": False,
        "tesseract_binary": False,
        "tesseract_path": "",
        "chi_sim": False,
        "message": "",
    }

    try:
        import pytesseract
        result["pytesseract"] = True
    except ImportError:
        result["message"] = t('error.pytesseract_missing')
        return jsonify(result)

    TESS_PATH = parsers.TESSERACT_PATH

    if not TESS_PATH:
        result["message"] = t('error.tesseract_missing')
        return jsonify(result)

    result["tesseract_binary"] = True
    result["tesseract_path"] = TESS_PATH
    pytesseract.pytesseract.tesseract_cmd = TESS_PATH

    try:
        langs = pytesseract.get_languages(config="")
        if "chi_sim" in langs:
            result["chi_sim"] = True
        else:
            result["message"] = t('error.chi_sim_missing')
    except Exception as e:
        result["message"] = t('error.lang_detect_fail').replace('{msg}', str(e))

    return jsonify(result)

@app.route("/api/check_ollama")
def api_check_ollama():
    import requests
    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    try:
        res = requests.get(f"{ollama_host}/api/tags", timeout=2, proxies={"http": None, "https": None})
        if res.status_code == 200:
            return jsonify({"ok": True, "msg": t('ollama.ok')})
        return jsonify({"ok": False, "msg": t('ollama.error')})
    except Exception:
        return jsonify({"ok": False, "msg": t('ollama.error')})

# ==================== AI 教研引擎闭环 ====================
@app.route("/api/generate_ai_paper", methods=["POST"])
def api_generate_ai_paper():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "msg": t('error.select_file')}), 400

    mode = request.form.get("mode", "reading")
    subject = request.form.get("subject", "auto")
    difficulty = request.form.get("difficulty", "normal")

    # 👇 新增：接收前端传来的题目数量
    try:
        question_count = int(request.form.get("count", 4))
        question_count = max(1, min(question_count, 20))  # 限制在 1-20 题
    except ValueError:
        question_count = 4

    current_lang = i18n.get_lang()
    fname = f.filename.lower()

    try:
        if fname.endswith(".pdf"):
            raw_text = parsers.extract_text_from_pdf(f.stream)
        elif fname.endswith(".docx"):
            raw_text = parsers.extract_text_from_docx(f.stream)
        elif fname.endswith(".txt"):
            raw_text = f.read().decode("utf-8", errors="ignore")
        else:
            return jsonify({"ok": False, "msg": t('error.unsupported_type')}), 400
    except Exception as e:
        return jsonify({"ok": False, "msg": t('error.read_fail').replace('{msg}', str(e))}), 400

    if len(raw_text) < 200:
        return jsonify({"ok": False, "msg": t('error.no_text')}), 400

    try:
        reading_data = parsers.generate_paper_from_text(
            raw_text,
            mode=mode,
            subject=subject,
            difficulty=difficulty,
            question_count=question_count,  # 👈 传入参数
            lang=current_lang
        )
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

    sid = uuid.uuid4().hex
    PARSE_CACHE[sid] = {"questions": [reading_data], "created_at": time.time()}

    return jsonify({"ok": True, "sid": sid, "msg": t('error.success')})

@app.route("/api/generate_ai_paper_stream", methods=["POST"])
def api_generate_ai_paper_stream():
    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "msg": t('error.select_file')}), 400

    mode = request.form.get("mode", "reading")
    subject = request.form.get("subject", "auto")
    difficulty = request.form.get("difficulty", "normal")
    try:
        question_count = int(request.form.get("count", 4))
        question_count = max(1, min(question_count, 20))
    except ValueError:
        question_count = 4

    current_lang = i18n.get_lang()
    fname = f.filename.lower()

    try:
        if fname.endswith(".pdf"):
            raw_text = parsers.extract_text_from_pdf(f.stream)
        elif fname.endswith(".docx"):
            raw_text = parsers.extract_text_from_docx(f.stream)
        elif fname.endswith(".txt"):
            raw_text = f.read().decode("utf-8", errors="ignore")
        else:
            return jsonify({"ok": False, "msg": t('error.unsupported_type')}), 400
    except Exception as e:
        return jsonify({"ok": False, "msg": t('error.read_fail').replace('{msg}', str(e))}), 400

    if len(raw_text) < 200:
        return jsonify({"ok": False, "msg": t('error.no_text')}), 400

    # 定义生成器，用于流式返回状态和最终结果
    def generate():
        def log_cb(msg):
            yield_data = json.dumps({"type": "log", "msg": msg}, ensure_ascii=False)
            yield f"data: {yield_data}\n\n"

        try:
            import time
            ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
            url = f"{ollama_host}/api/generate"

            prompt = parsers._build_paper_prompt(raw_text, mode, subject, difficulty, question_count, current_lang)

            max_retries = 3
            final_data = None

            for attempt in range(max_retries):
                # 👇 核心修复 1：每次循环前，检查客户端是否已经断开连接
                # 如果用户关了网页，这里会变成 True，直接跳出循环，节省算力
                if hasattr(request, 'is_disconnected') and request.is_disconnected():
                    print("[Stream] 客户端已断开连接，停止生成。")
                    break

                yield f"data: {json.dumps({'type': 'log', 'msg': t('ai.try', n=question_count, i=attempt + 1)}, ensure_ascii=False)}\n\n"

                payload = {
                    "model": os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"),
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.7}
                }
                try:
                    import requests
                    res = requests.post(url, json=payload, timeout=120, proxies={"http": None, "https": None})
                    result_text = res.json().get("response", "")
                    result_text = result_text.replace("```json", "").replace("```", "").strip()
                    data = json.loads(result_text)

                    if data.get("article"):
                        data["article"] = data["article"].replace("处理后的文章内容（完形填空请带空）", "").replace(
                            "处理后的文章内容", "").strip()

                    generated_questions = data.get("questions", [])
                    if len(generated_questions) == question_count:
                        yield f"data: {json.dumps({'type': 'log', 'msg': t('ai.ok', n=question_count)}, ensure_ascii=False)}\n\n"
                        final_data = data
                        break
                    else:
                        yield f"data: {json.dumps({'type': 'log', 'msg': t('ai.lazy', got=len(generated_questions))}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'log', 'msg': t('ai.fail', i=attempt + 1, msg=e)}, ensure_ascii=False)}\n\n"

            if final_data:
                sid = uuid.uuid4().hex
                PARSE_CACHE[sid] = {"questions": [final_data], "created_at": time.time()}
                yield f"data: {json.dumps({'type': 'done', 'sid': sid}, ensure_ascii=False)}\n\n"
            else:
                # 👇 核心修复 2：如果是因为客户端断开导致的跳出，这里直接 return 不要报错
                if hasattr(request, 'is_disconnected') and request.is_disconnected():
                    return
                yield f"data: {json.dumps({'type': 'error', 'msg': t('error.ai_retry_exhausted')}, ensure_ascii=False)}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'msg': str(e)}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream")

@app.route("/reading/<sid>")
def reading_page(sid):
    return render_template("reading_exam.html", sid=sid)


@app.route("/export_reading_word/<sid>")
def export_reading_word(sid):
    cache = PARSE_CACHE.get(sid)
    if not cache or not cache["questions"]:
        return t('error.expired'), 404

    reading_data = cache["questions"][0]

    doc = Document()
    current_lang = i18n.get_lang()
    if current_lang == "ja_JP":
        font_name = 'MS Gothic'  # 日文
    elif current_lang == "en_US":
        font_name = 'Times New Roman'  # 英文
    else:
        font_name = '宋体'  # 中文

    doc.styles['Normal'].font.name = font_name
    doc.styles['Normal']._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)
    doc.styles['Normal'].font.size = Pt(12)

    # 👇 给标题也加上清洗
    title = doc.add_heading(clean_xml_string(reading_data.get("title", t('reading.title'))), level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    p_article = doc.add_paragraph()
    p_article.paragraph_format.first_line_indent = Cm(0.74)
    p_article.paragraph_format.line_spacing = 1.5
    # 👇 清洗文章
    p_article.add_run(clean_xml_string(reading_data.get("article", "")))

    doc.add_paragraph(" ")

    for idx, q in enumerate(reading_data.get("questions", []), 1):
        p_q = doc.add_paragraph()
        p_q.paragraph_format.space_before = Pt(12)
        # 👇 清洗题干
        p_q.add_run(clean_xml_string(q["question"])).bold = True

        if q.get("options"):
            for i, opt in enumerate(q["options"]):
                p_opt = doc.add_paragraph()
                p_opt.paragraph_format.left_indent = Cm(1)
                # 👇 清洗选项
                p_opt.add_run(clean_xml_string(opt))

        if q["type"] == "short":
            doc.add_paragraph("\n\n\n\n")

    file_stream = io.BytesIO()
    doc.save(file_stream)
    file_stream.seek(0)

    # 动态获取多语言标题
    doc_title = reading_data.get('title', t('reading.title'))

    # 👇 新增：清洗 Windows/Mac 下不允许作为文件名的特殊字符
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', doc_title)
    file_name = f"{t('reading.title')}_{safe_title}.docx"

    return send_file(
        file_stream,
        as_attachment=True,
        download_name=file_name,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

# ==================== 启动 ====================
def _pick_port(preferred=5001, tries=20):
    """优先用 5001；被占用就往后找一个空闲端口，避免二次启动直接崩"""
    import socket
    for p in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return preferred


def _setup_log_file():
    """打包成窗口程序后没有控制台，把 stdout/stderr 落到数据目录的 app.log"""
    if not getattr(sys, "frozen", False):
        return
    try:
        f = open(os.path.join(get_data_dir(), "app.log"), "a", encoding="utf-8", buffering=1)
    except Exception:
        class _Sink:
            def write(self, *a):
                pass

            def flush(self):
                pass
        f = _Sink()
    sys.stdout = f
    sys.stderr = f
    print("\n" + "=" * 50)
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] 智卷启动")


def open_in_browser(url, delay=2.5):
    """用系统默认浏览器打开页面（多种兜底）"""
    if delay:
        time.sleep(delay)
    try:
        if webbrowser.open(url):
            print(f"[OK] 已用默认浏览器打开：{url}")
            return
    except Exception as e:
        print(f"[WARN] webbrowser 失败：{e}")

    import subprocess
    try:
        if sys.platform == "win32":
            os.startfile(url)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
        print(f"[OK] 已用系统命令打开：{url}")
        return
    except Exception as e:
        print(f"[WARN] 系统命令失败：{e}")

    print("=" * 50)
    print("⚠️ 无法自动打开浏览器")
    print(f"请手动复制以下地址到浏览器：{url}")
    print("=" * 50)


def print_banner(url):
    print("=" * 50)
    print("   智卷 · 智能题库系统")
    print("   ────────────────────────")
    print(f"   地址：{url}")
    print("   数据目录：", get_data_dir())
    print("=" * 50)

    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            print("   ✅ 本地 AI 引擎 (Ollama) 已连接")
        else:
            raise Exception()
    except Exception:
        print("   ⚠️ 警告：本地 AI 引擎 (Ollama) 未启动！")
        print("      如果您需要使用 AI 解析或生成变式题，请另开一个 CMD 运行：")
        print("      👉 ollama run qwen2.5:3b")
    print("=" * 50)


def run_server(port):
    """阻塞式启动 Flask（桌面壳与浏览器模式共用）"""
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    _setup_log_file()

    env_port = os.environ.get("PORT")
    port = int(env_port) if env_port else _pick_port(5001)
    url = f"http://127.0.0.1:{port}"

    init_db()
    print_banner(url)

    # 默认开原生窗口；加 --browser 可强制走浏览器模式
    if "--browser" not in args:
        try:
            from desktop import run_desktop
            status = run_desktop(url, port, run_server)
        except Exception as e:
            print(f"[WARN] 桌面窗口启动失败：{e}")
            status = "unavailable"

        if status == "ok":
            return 0
        if status == "degraded":
            # 窗口挂了，但服务已在后台线程跑起来了：退化成浏览器模式
            open_in_browser(url, delay=0)
            threading.Event().wait()
            return 0
        print("[WARN] 桌面窗口不可用，回退到浏览器模式")

    threading.Thread(target=open_in_browser, args=(url,), daemon=True).start()
    run_server(port)
    return 0


if __name__ == "__main__":
    sys.exit(main())