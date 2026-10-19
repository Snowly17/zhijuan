# -*- coding: utf-8 -*-
"""
题库文件解析器：把 docx/pdf 解析成结构化题目
- 支持单行选项、多行选项、内联选项（A.xxxB.xxx）
- 支持题干括号答案（A）/ 尾行答案（正确答案: A）
- 支持判断题（正确/错误行）
- 支持多行解析合并
- 自动跳过图片题
- OCR 常见错字修正
- Tesseract 路径自动查找（跨平台）
"""
import re
import os
import shutil
import requests

from i18n import t


# ==================== Tesseract 配置（跨平台自动查找） ====================
def _find_tesseract():
    """
    自动查找 Tesseract 可执行文件：
      1. 环境变量 TESSERACT_PATH
      2. 系统 PATH
      3. 各平台常见默认路径
    找不到返回 None
    """
    # 1. 环境变量优先
    env_path = os.environ.get("TESSERACT_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # 2. 系统 PATH
    which = shutil.which("tesseract")
    if which:
        return which

    # 3. 各系统常见安装位置
    candidates = [
        # Windows 默认
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        # Linux
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        # macOS（Homebrew）
        "/opt/homebrew/bin/tesseract",
        "/usr/local/Cellar/tesseract/bin/tesseract",
        # 用户目录
        os.path.expanduser("~/Tesseract-OCR/tesseract.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p

    return None


TESSERACT_PATH = _find_tesseract()

if TESSERACT_PATH:
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    except ImportError:
        pass


def ocr_available():
    """检查 OCR 是否可用，返回 (是否可用, 英文日志/错误码)"""
    if not TESSERACT_PATH:
        return False, "Tesseract-OCR binary not found."
    if not os.path.exists(TESSERACT_PATH):
        return False, f"Tesseract path not exist: {TESSERACT_PATH}"
    try:
        import pytesseract
    except ImportError:
        return False, "pytesseract not installed."
    try:
        langs = pytesseract.get_languages(config="")
        if "chi_sim" not in langs:
            return False, "Missing 'chi_sim' language pack."
    except Exception as e:
        return False, f"Language detect failed: {e}"
    return True, "OK"


# ==================== 正则区 ====================
RE_QNUM = re.compile(r'^\s*(\d+)\s*[.、\．\)）]\s*(.+)$')

RE_TYPE_LINE = re.compile(
    r'^\s*[【\[]?\s*(单选题|多选题|判断题|填空题|简答题|单选|多选|判断|填空|简答)'
    r'\s*[】\]]?\s*$'
)

RE_OPTION = re.compile(r'^\s*([A-H])\s*[.、\．\)）]\s*(.+)$')

RE_ANSWER = re.compile(
    r'^\s*[#\*]*\s*(?:正确答案|参考答案|答案)'
    r'\s*[:：]\s*(.+?)\s*$'
)

RE_ANALYSIS = re.compile(
    r'^\s*[#\*]*\s*(?:解析|分析|答案解析)'
    r'\s*[:：]\s*(.*)$'
)

RE_TYPE_TAG = re.compile(
    r'【(单选题|多选题|判断题|填空题|简答题|无线考点|安全考点|网络考点|VLAN考点|数通考点)】'
)

# 题干末尾括号答案：（A） / (ABCD) / （正确）
RE_TRAILING_ANSWER = re.compile(
    r'[（\(]\s*([A-H]{1,8}|正确|错误|对|错|T|F|√|×)\s*[）\)]\s*[。.．]?\s*$'
)

# 图片题识别（收紧版：只匹配明确提到"图"的）
RE_HAS_IMAGE = re.compile(
    r'(如图所示|如下图所?示?|如图所?示?|见图所示|见下图|见上图|上图所示|下图所示)'
)

# 内联选项标记：行首必须是 A.
RE_INLINE_MARK_HEAD = re.compile(r'^([A-H])\s*[.、\．\)）]\s*')
RE_INLINE_MARK_ALL = re.compile(r'([A-H])\s*[.、\．\)）]\s*')


# ==================== OCR 常见错字修正 ====================
OCR_FIX = {
    "0SPF": "OSPF", "0spf": "ospf",
    "ARF": "ARP",
    "lP地址": "IP地址",
    "vlAN": "VLAN", "Vlan": "VLAN",
    "Eth- Trunk": "Eth-Trunk", "Eth- trunk": "Eth-Trunk",
    "capwap": "CAPWAP", "CAMPWAP": "CAPWAP",
    "FITAP": "FIT AP", "FATAP": "FAT AP",
    "ospf": "OSPF", "bgp": "BGP", "rip": "RIP",
    "isis": "IS-IS", "acl": "ACL", "dhcp": "DHCP",
    "stp": "STP", "rstp": "RSTP", "mstp": "MSTP",
}


# ==================== 工具函数 ====================
def _clean(s):
    if s is None:
        return ""
    s = s.replace('\u3000', ' ').strip()
    s = re.sub(r'\s+', ' ', s)
    return s


def _fix_ocr(text):
    if not text:
        return text
    for wrong, right in OCR_FIX.items():
        text = text.replace(wrong, right)
    return text


def _normalize_answer(raw):
    if raw is None:
        return None
    s = str(raw).strip().strip('。.；;，,')

    upper = s.upper()
    if upper in ("正确", "对", "TRUE", "T", "√", "是"):
        return "T"
    if upper in ("错误", "错", "FALSE", "F", "×", "否"):
        return "F"

    parts = re.split(r'[,，、\s]+', s)
    parts = [p.strip().upper() for p in parts if p.strip()]
    if len(parts) > 1 and all(len(p) == 1 and p in "ABCDEFGH" for p in parts):
        return parts

    if len(s) > 1 and all(c.upper() in "ABCDEFGH" for c in s):
        return [c.upper() for c in s]

    return s.upper()


def _extract_answer(block_lines):
    for line in block_lines:
        m = RE_ANSWER.match(line)
        if m:
            return _normalize_answer(m.group(1))
    return None


def _extract_trailing_answer(question):
    m = RE_TRAILING_ANSWER.search(question)
    if not m:
        return question, None
    raw = m.group(1)
    cleaned = question[:m.start()].strip()
    return cleaned, _normalize_answer(raw)


def _type_from_label(label):
    if "多选" in label:
        return "multiple"
    if "判断" in label:
        return "judge"
    if "填空" in label:
        return "blank"
    if "简答" in label:
        return "short"
    return "single"


def _detect_type(block_lines, options, answer):
    joined = " ".join(block_lines)
    m = RE_TYPE_TAG.search(joined)
    if m:
        return _type_from_label(m.group(1))

    if options:
        if isinstance(answer, list) and len(answer) > 1:
            return "multiple"
        if isinstance(answer, str) and len(answer) > 1 \
                and all(c in "ABCDEFGH" for c in answer.upper()):
            return "multiple"
        return "single"

    if isinstance(answer, str) and answer in ("T", "F"):
        return "judge"

    if "____" in joined:
        return "blank"

    return "single"


# ==================== 内联选项拆分 ====================
def _split_inline_options(line):
    """
    把 'A.xxx B.xxx C.xxx D.xxx' 一行拆成 ['xxx','xxx','xxx','xxx']

    多层防御：
      1. 行首必须是 A.
      2. 至少 3 个标记
      3. 字母必须严格 A,B,C,D... 连续递增
      4. 每个选项内容 1—200 字符
      5. 选项内容里不能再嵌套 A. B.
      6. 整行不能超过 2000 字符
    """
    if not line:
        return None
    if len(line) > 2000:
        return None

    head = RE_INLINE_MARK_HEAD.match(line)
    if not head or head.group(1) != 'A':
        return None

    marks = list(RE_INLINE_MARK_ALL.finditer(line))
    if len(marks) < 3:
        return None

    letters = [m.group(1) for m in marks]
    expected = [chr(ord('A') + i) for i in range(len(letters))]
    if letters != expected:
        return None

    opts = []
    for i, m in enumerate(marks):
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(line)
        content = line[start:end].strip().rstrip('，,。.；;')
        if not content or len(content) > 200:
            return None
        if RE_INLINE_MARK_HEAD.match(content):
            return None
        opts.append(content)

    return opts if len(opts) >= 3 else None


# ==================== 单题解析 ====================
JUDGE_WORDS = {"正确", "错误", "对", "错", "True", "False", "√", "×"}


def _parse_one_block(block, forced_type=None):
    if not block:
        return None

    # ===== 题号 =====
    qnum = None
    for line in block:
        m = RE_QNUM.match(line)
        if m:
            try:
                qnum = int(m.group(1))
            except ValueError:
                pass
            break

    # ===== 定位「解析：」行 =====
    analysis_start = -1
    for i, line in enumerate(block):
        if RE_ANALYSIS.match(line):
            analysis_start = i
            break

    if analysis_start >= 0:
        main_lines = block[:analysis_start]
        analysis_lines = block[analysis_start:]
    else:
        main_lines = block
        analysis_lines = []

    # ===== 多行解析合并 =====
    analysis = ""
    if analysis_lines:
        first = RE_ANALYSIS.match(analysis_lines[0])
        first_content = first.group(1) if first else ""
        rest = analysis_lines[1:]
        analysis = " ".join(p for p in ([first_content] + rest) if p).strip()
        analysis = re.sub(r'\s+', ' ', analysis).strip()

    # ===== 遍历 main_lines =====
    question = ""
    options = []
    judge_opts = []
    body_lines = []

    for line in main_lines:
        qm = RE_QNUM.match(line)
        if qm and not question:
            question = qm.group(2).strip()
            continue
        if RE_ANSWER.match(line):
            continue

        # 内联选项优先
        inline_opts = _split_inline_options(line)
        if inline_opts:
            options.extend(inline_opts)
            continue

        om = RE_OPTION.match(line)
        if om:
            options.append(om.group(2).strip())
            continue
        if line in JUDGE_WORDS:
            judge_opts.append(line)
            continue
        body_lines.append(line)

    # 判断题：有"正确"+"错误"两行 → 作为选项
    if len(judge_opts) >= 2 and not options:
        options = judge_opts
        forced_type = forced_type or "judge"

    if not question and body_lines:
        question = body_lines.pop(0)
    if body_lines:
        question = (question + " " + " ".join(body_lines)).strip()

    question = RE_TYPE_TAG.sub('', question).strip()
    question = _fix_ocr(question)
    question = re.sub(r'\s+', ' ', question).strip()

    if not question:
        return None
    if RE_HAS_IMAGE.search(question):
        return None

    # ===== 答案 =====
    answer = _extract_answer(main_lines)
    if answer is None:
        question, answer = _extract_trailing_answer(question)
    if answer is None:
        return None

    # ===== 题型判定 =====
    qtype = forced_type or _detect_type(main_lines, options, answer)

    if qtype == "single" and isinstance(answer, list):
        qtype = "multiple"
    if qtype == "multiple" and isinstance(answer, str) and len(answer) == 1:
        qtype = "single"

    if qtype == "judge":
        if answer not in ("T", "F"):
            up = str(answer).upper()
            if up in ("A", "TRUE", "T", "正确", "对"):
                answer = "T"
            elif up in ("B", "FALSE", "F", "错误", "错"):
                answer = "F"
            else:
                return None

    if qtype in ("blank", "short"):
        if isinstance(answer, str):
            parts = [p.strip() for p in re.split(r'[|/、]', answer) if p.strip()]
            answer = parts if parts else [answer]

    result = {
        "type": qtype,
        "question": question,
        "options": options,
        "answer": answer,
        "score": 2,
        "analysis": analysis,
    }
    if qnum is not None:
        result["_qnum"] = qnum
    return result


# ==================== 全文解析 ====================
def parse_question_text(text):
    lines = [_clean(l) for l in text.split('\n')]
    lines = [l for l in lines if l]

    questions = []
    current = []
    current_type = None

    def flush():
        nonlocal current, current_type
        if current:
            q = _parse_one_block(current, current_type)
            if q:
                questions.append(q)
        current = []
        current_type = None

    for line in lines:
        tm = RE_TYPE_LINE.match(line)
        if tm:
            flush()
            current_type = _type_from_label(tm.group(1))
            continue

        qm = RE_QNUM.match(line)
        if qm:
            flush()
            current = [line]
            continue

        current.append(line)

    flush()
    return questions


def _merge_orphan_answers(questions):
    """兜底：某道题没答案，但下一道题解析区里有答案，就近补上"""
    for i, q in enumerate(questions):
        if q.get("answer") is None and i + 1 < len(questions):
            next_analysis = questions[i + 1].get("analysis", "")
            m = RE_ANSWER.search(next_analysis)
            if m:
                q["answer"] = _normalize_answer(m.group(1))
                questions[i + 1]["analysis"] = next_analysis[m.end():].strip()
    return questions


def analyze_qnums(raw_text, questions):
    """对比原文题号和已解析题号，返回缺失列表"""
    text_qnums = set()
    for line in raw_text.split("\n"):
        m = RE_QNUM.match(line.strip())
        if m:
            try:
                text_qnums.add(int(m.group(1)))
            except ValueError:
                pass

    parsed_qnums = set()
    for q in questions:
        if isinstance(q, dict) and "_qnum" in q:
            parsed_qnums.add(q["_qnum"])

    if not text_qnums:
        return {"text_qnums": [], "parsed_qnums": [], "missing": []}

    max_q = max(text_qnums)
    missing = sorted(
        n for n in range(1, max_q + 1)
        if n in text_qnums and n not in parsed_qnums
    )
    return {
        "text_qnums": sorted(text_qnums),
        "parsed_qnums": sorted(parsed_qnums),
        "missing": missing,
    }


# ==================== 文本提取 ====================
# 找到 extract_text_from_pdf 函数，整个替换为：

def extract_text_from_pdf(file_stream):
    """只做文本提取，不解析"""
    file_stream.seek(0)

    # 1. 优先尝试 PyMuPDF (fitz)
    try:
        import fitz
        data = file_stream.read()
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            parts = [page.get_text("text") for page in doc]
        finally:
            doc.close()
        return "\n".join(parts)
    except ImportError:
        pass
    except Exception as e:
        print(f"[PDF] PyMuPDF 解析失败: {e}")

    # 2. 其次尝试 pdfplumber
    try:
        import pdfplumber
        file_stream.seek(0)
        with pdfplumber.open(file_stream) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except ImportError:
        pass
    except Exception as e:
        print(f"[PDF] pdfplumber 解析失败: {e}")

    # 3. 兜底尝试 PyPDF2
    try:
        from PyPDF2 import PdfReader
        file_stream.seek(0)
        reader = PdfReader(file_stream)
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except ImportError:
        raise RuntimeError(t('error.pdf_lib_missing'))
    except Exception as e:
        raise RuntimeError(t('error.parse_fail').replace('{msg}', str(e)))


def extract_text_from_pdf_ocr(file_stream, max_pages=None):
    """用 OCR 从 PDF 中提取文本（扫描件用）"""
    ok, msg = ocr_available()
    if not ok:
        raise RuntimeError(t('error.ocr_not_ready').replace('{msg}', msg))

    try:
        import fitz
        import pytesseract
        from PIL import Image
        import io
    except ImportError as e:
        raise RuntimeError(
            t('error.ocr_deps_missing')
            + "\n"
            + t('error.read_fail').replace('{msg}', str(e))
        )

    file_stream.seek(0)
    data = file_stream.read()
    doc = fitz.open(stream=data, filetype="pdf")

    parts = []
    try:
        total = len(doc)
        limit = min(total, max_pages) if max_pages else total
        for i in range(limit):
            page = doc[i]
            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            parts.append(text)
    finally:
        doc.close()

    return "\n".join(parts)


def extract_text_from_docx(file_stream):
    from docx import Document
    doc = Document(file_stream)
    lines = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    if para.text.strip():
                        lines.append(para.text)
    return "\n".join(lines)


# ==================== 文件级解析 ====================
def parse_docx(file_stream):
    text = extract_text_from_docx(file_stream)
    questions = parse_question_text(text)
    return _merge_orphan_answers(questions)


def parse_pdf(file_stream):
    text = extract_text_from_pdf(file_stream)

    lines = [l for l in text.split("\n") if l.strip()]
    if len(lines) < 50:
        try:
            print(f"[PDF] 原生提取只有 {len(lines)} 行，尝试 OCR…")
            file_stream.seek(0)
            text = extract_text_from_pdf_ocr(file_stream, max_pages=20)
            print(f"[PDF] OCR 提取完成")
        except Exception as e:
            print(f"[PDF] OCR 失败，退回原生文本：{e}")

    questions = parse_question_text(text)
    return _merge_orphan_answers(questions)


def extract_with_ai(raw_text, model=None, lang="zh_CN"):
    """使用本地 Ollama 解析纯文本题库（分段循环版，支持多语言）"""
    import json
    import os
    import requests

    if model is None:
        model = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

    ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    url = f"{ollama_host}/api/generate"

    # 按行切分，每 3000 字符左右打成一段
    lines = raw_text.split('\n')
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        current_chunk.append(line)
        current_len += len(line)
        if current_len > 3000:
            chunks.append('\n'.join(current_chunk))
            current_chunk = []
            current_len = 0
    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    out = []

    # 构建多语言 Prompt
    if lang == "en_US":
        prompt_template = """
        You are a highly rigorous quiz parser. 
        Please extract the questions from the text below and output them as a JSON array.

        Requirements:
        1. Each question is an object with fields: type, question, options, answer, analysis.
        2. The "type" field MUST be exactly one of: "single", "multiple", "judge", "blank", "short".
        3. The "options" field must be an array of strings, e.g., ["A. xxx", "B. xxx"].
        4. The "answer" for multiple choice should be comma-separated (e.g., "A,B"). For judge, use "T" or "F". For blank/short, just the answer text.
        5. If there is no analysis in the text, leave the "analysis" field as an empty string.
        6. Output ONLY a valid JSON array. No markdown formatting, no extra explanations.
        7. CRITICAL: The generated text MUST be in English.

        Text to parse:
        {text_slice}
        """
    elif lang == "ja_JP":
        prompt_template = """
        あなたは非常に厳密なクイズパーサーです。
        以下のテキストから問題を抽出し、JSON配列として出力してください。

        【要件】
        1. 各問題はオブジェクトであり、フィールドは：type, question, options, answer, analysis です。
        2. type は "single", "multiple", "judge", "blank", "short" のいずれかでなければなりません。
        3. options は文字列の配列である必要があります（例：["A. xxx", "B. xxx"]）。
        4. multipleのanswerはカンマ区切り（例："A,B"）。judgeの場合は "T" または "F"。blank/shortの場合は回答テキストのみ。
        5. analysis がない場合は空文字列にしてください。
        6. 有効な JSON 配列のみを出力してください。マークダウンや説明は不要です。
        7. 重要：生成されるテキストはすべて【日本語】で出力してください。

        解析するテキスト：
        {text_slice}
        """
    else:
        # 默认中文
        prompt_template = """
        你是一个极其严谨的题库解析器。请提取以下文本中的题目，输出为 JSON 数组格式。

        要求：
        1. 每道题是一个对象，包含字段：type, question, options, answer, analysis。
        2. type 只能填："single", "multiple", "judge", "blank", "short"。
        3. options 格式为数组，如：["A. xxx", "B. xxx"]。
        4. answer 多选题用逗号分隔（如 "A,B"），判断题填 "T" 或 "F"，填空题/简答题直接填答案文本。
        5. 如果文本中没有解析，analysis 字段留空。
        6. 必须只输出合法的 JSON 数组，不要输出任何 Markdown 标记或额外解释。
        7. 重要：生成的 question、options、analysis 必须使用【中文】。

        待解析文本：
        {text_slice}
        """

    for i, text_slice in enumerate(chunks, 1):
        print(f"[AI] 正在解析第 {i}/{len(chunks)} 段...")

        prompt = prompt_template.replace("{text_slice}", text_slice)

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }

        try:
            response = requests.post(url, json=payload, timeout=180, proxies={"http": None, "https": None})
            response.raise_for_status()
            result_text = response.json().get("response", "")

            if not result_text:
                continue

            # 👇 调用升级后的防弹解析器
            questions = _parse_ai_response(result_text)
            if isinstance(questions, dict):
                questions = questions.get("questions", [])

            for q in questions:
                norm = {
                    "type": q.get("type", "single"),
                    "question": q.get("question", "").strip(),
                    "options": q.get("options", []),
                    "answer": q.get("answer", ""),
                    "score": 2,
                    "analysis": q.get("analysis", "")
                }
                if norm["question"] and norm["answer"]:
                    out.append(norm)
        except requests.exceptions.ConnectionError:
            raise RuntimeError(t('error.ollama_unreachable'))
        except Exception as e:
            print(f"[AI] 第 {i} 段解析失败: {e}")
            continue

    return out


def _parse_ai_response(text):
    """清理 AI 返回的文本并鲁棒地解析为 JSON"""
    import json
    import re
    if not text:
        return []

    # 去除 markdown 标记
    text = text.replace("```json", "").replace("```", "").strip()

    # 1. 尝试直接解析
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "questions" in data:
            return data["questions"]
        return data
    except json.JSONDecodeError:
        pass

    # 2. 兜底：正则强行抠出最外层的 []
    try:
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            return json.loads(match.group(0))
    except:
        pass

    # 3. 兜底：正则强行抠出最外层的 {}
    try:
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            return json.loads(match.group(0))
    except:
        pass

    raise ValueError(t('error.ai_invalid_json'))

def _build_paper_prompt(text, mode, subject, difficulty, question_count, lang):
    lang_map = {"zh_CN": "中文", "en_US": "English", "ja_JP": "日本語"}
    target_lang = lang_map.get(lang, "中文")
    if subject == "zh": target_lang = "中文"
    elif subject == "en": target_lang = "English"

    if mode == "cloze":
        task = f"生成一份【完形填空】。将文章中 {question_count} 个核心词汇替换为 '____'，并生成 {question_count} 道单项选择题。"
        example_q = "请选择最适合填入空格 1 的单词。"
    elif mode == "short":
        task = f"生成一份【主观简答题】。提炼文中 {question_count} 个核心知识点，生成问答题。"
        example_q = "请简述文章的主要观点。"
    else:
        single_count = question_count - 1 if question_count > 1 else 1
        task = f"生成一份【阅读理解】。包含 {single_count} 道单选题和 1 道简答题（共 {question_count} 道题）。"
        example_q = "What is the main idea of the passage?"

    diff_desc = {"easy": "简单（直接考察原文细节）", "normal": "中等（需要理解和归纳）", "hard": "困难（需要深度推断或结合上下文）"}
    target_diff = diff_desc.get(difficulty, "中等")

    return f"""
    你是一位资深的【{target_lang}】教研员。请根据我提供的【文档内容】，{task}

    【命题要求】
    1. 难度等级：{target_diff}。
    2. **重要约束**：你必须且只能输出 {question_count} 道题目！绝不能少，也不能多。
    3. **语言一致性**：请严格使用【{target_lang}】输出所有内容。如果正文是英文，文章标题也必须使用英文，绝不能翻译成中文！
    4. **极其重要**：不要输出任何模板里的占位符（比如“题干？”、“处理后的文章内容”等），必须自己根据文章创作具体的题目！
    5. **选项不能重复**，必须提供 4 个不同的选项（ABCD）。
    6. 必须输出纯 JSON 格式，不要带 Markdown 标记。

    【JSON 格式要求】
    {{
      "type": "{mode}",
      "paper_title": "给这份试卷起一个标题（使用{target_lang}）",
      "article_title": "文章原本的标题（如果原文没有，请使用{target_lang}总结一个，如果是英文文章，绝不能出现中文！）",
      "article": "只放处理后的正文，不要包含说明文字",
      "questions": [
        {{
          "type": "single",
          "question": "{example_q}",
          "options": ["A. 具体选项1", "B. 具体选项2", "C. 具体选项3", "D. 具体选项4"],
          "answer": "A",
          "analysis": "具体的解析..."
        }}
      ]
    }}

    【文档内容】
    {text[:4000]}
    """

def generate_paper_from_text(text, mode="reading", subject="auto", difficulty="normal", question_count=4,
                             engine="ollama", lang="zh_CN", log_callback=None):
    if len(text) > 8000:
        text_slice = text[:8000]
        last_para = text_slice.rfind('\n')
        if last_para > 7000:
            text_slice = text_slice[:last_para]
        # 根据语言判断
        if lang == "en_US":
            text_slice += "\n\n(Note: The text is too long, only the first part is intercepted.)"
        elif lang == "ja_JP":
            text_slice += "\n\n(注：テキストが長すぎるため、前部のみを抽出しています。)"
        else:
            text_slice += "\n\n(注：由于文章过长，已截取前部核心内容)"
    else:
        text_slice = text

    def _log(msg):
        print(msg)  # 依然在终端打印
        if log_callback:
            log_callback(msg)  # 同时发给前端

    lang_map = {"zh_CN": "中文", "en_US": "English", "ja_JP": "日本語"}
    target_lang = lang_map.get(lang, "中文")
    if subject == "zh":
        target_lang = "中文"
    elif subject == "en":
        target_lang = "English"

    if mode == "cloze":
        task = f"生成一份【完形填空】。将文章中 {question_count} 个核心词汇替换为 '____'，并生成 {question_count} 道单项选择题。"
        example_q = "请选择最适合填入空格 1 的单词。"
    elif mode == "short":
        task = f"生成一份【主观简答题】。提炼文中 {question_count} 个核心知识点，生成问答题。"
        example_q = "请简述文章的主要观点。"
    else:
        single_count = question_count - 1 if question_count > 1 else 1
        task = f"生成一份【阅读理解】。包含 {single_count} 道单选题和 1 道简答题（共 {question_count} 道题）。"
        example_q = "What is the main idea of the passage?"

    diff_desc = {"easy": "简单（直接考察原文细节）", "normal": "中等（需要理解和归纳）",
                 "hard": "困难（需要深度推断或结合上下文）"}
    target_diff = diff_desc.get(difficulty, "中等")

    prompt = f"""
    你是一位资深的【{target_lang}】教研员。请根据我提供的【文档内容】，{task}

    【命题要求】
    1. 难度等级：{target_diff}。
    2. **重要约束**：你必须且只能输出 {question_count} 道题目！绝不能少，也不能多。
    3. **语言一致性**：请严格使用【{target_lang}】输出所有内容。如果正文是英文，文章标题也必须使用英文，绝不能翻译成中文！
    4. **极其重要**：不要输出任何模板里的占位符（比如“题干？”、“处理后的文章内容”等），必须自己根据文章创作具体的题目！
    5. **选项不能重复**，必须提供 4 个不同的选项（ABCD）。
    6. 必须输出纯 JSON 格式，不要带 Markdown 标记。

    【JSON 格式要求】
    {{
      "type": "{mode}",
      "paper_title": "给这份试卷起一个标题（使用{target_lang}）",
      "article_title": "文章原本的标题（如果原文没有，请使用{target_lang}总结一个，如果是英文文章，绝不能出现中文！）",
      "article": "只放处理后的正文，不要包含说明文字",
      "questions": [
        {{
          "type": "single",
          "question": "{example_q}",
          "options": ["A. 具体选项1", "B. 具体选项2", "C. 具体选项3", "D. 具体选项4"],
          "answer": "A",
          "analysis": "具体的解析..."
        }}
      ]
    }}

    【文档内容】
    {text_slice}
    """

    if engine == "ollama":
        import requests, os, json
        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        url = f"{ollama_host}/api/generate"

        max_retries = 3
        for attempt in range(max_retries):
            _log(t('ai.try', n=question_count, i=attempt + 1))
            payload = {
                "model": os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"),
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.7
                }
            }
            try:
                res = requests.post(url, json=payload, timeout=180, proxies={"http": None, "https": None})
                result_text = res.json().get("response", "")

                # 👇 调用升级后的防弹解析器
                data = _parse_ai_response(result_text)

                if data.get("article"):
                    data["article"] = data["article"].replace("处理后的文章内容（完形填空请带空）", "").replace(
                        "处理后的文章内容", "").strip()

                generated_questions = data.get("questions", [])
                if len(generated_questions) == question_count:
                    _log(t('ai.ok', n=question_count))
                    return data
                else:
                    _log(t('ai.lazy', got=len(generated_questions)))
            except Exception as e:
                _log(t('ai.fail', i=attempt + 1, msg=e))

        _log(t('error.ai_retry_exhausted'))
        if 'data' in locals():
            return data
        else:
            raise RuntimeError(t('error.ai_gen_failed'))

def generate_variant_question(orig_question, engine="ollama"):
    """根据原题生成变式题"""
    prompt = f"""
    你是一位资深的命题专家。请针对以下原题，生成一道【举一反三】的变式题。

    【原题内容】
    {orig_question}

    【要求】
    1. 考查的核心知识点必须与原题完全一致。
    2. 必须改变题目的场景、数值或提问角度，不能是原题的简单重复。
    3. 必须是一道单选题，给出 4 个选项（ABCD）。
    4. 必须输出纯 JSON 格式，不要任何 Markdown 标记。

    【JSON 格式要求】
    {{
      "question": "题干内容",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "answer": "A",
      "analysis": "解析..."
    }}
    """

    if engine == "ollama":
        import requests
        import os
        import json

        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        url = f"{ollama_host}/api/generate"
        payload = {
            "model": os.environ.get("OLLAMA_MODEL", "qwen2.5:3b"),
            "prompt": prompt,
            "stream": False,
            "format": "json"
        }
        try:
            res = requests.post(url, json=payload, timeout=60, proxies={"http": None, "https": None})
            res.raise_for_status()
            result_text = res.json().get("response", "")

            # 👇 调用升级后的防弹解析器
            return _parse_ai_response(result_text)
        except Exception as e:
            raise RuntimeError(str(e))



# ==================== 调试 ====================
if __name__ == "__main__":
    print(f"[DEBUG] Tesseract 路径：{TESSERACT_PATH}")
    ok, msg = ocr_available()
    print(f"[DEBUG] OCR 可用性：{'可用' if ok else '不可用'} —— {msg}")

