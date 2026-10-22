# -*- coding: utf-8 -*-
"""
OCR 容错解析器（扫描件专用）

背景
----
Tesseract 在 96 DPI 的扫描件上会把"结构标记"打坏，实测（你的测试文档.pdf, 235 页）：
    "1.题干"      -> "1,题干" / "1题干"    题号分隔符丢失或变形
    "2.题干"      -> "了.题干"            题号数字被识别成汉字
    "9.题干"      -> "S.题干"             题号数字被识别成字母
    "24.题干"     -> "2a.题干"            题号带尾巴
    "11.题干"     -> "11VRP题干"          题号与题干粘连
    "54.题干"     -> "54,题干"            分隔符变成逗号
    "A.正确"      -> "ATrue" / "人正确"   选项分隔符丢失，字母被认成汉字
    "(A)"          -> "(A) 【判断题"      答案后粘着题型标签
    "(A)"          -> "( \n A) 【单选题】" 答案被拆到下一行
    "参考答案：B"  -> "参考答案 B"          冒号丢失
    "【多选题】"    -> "【多选是"           题型标签被误识别

设计原则（沿用 docs/解析器工作原理.md 的"三条底线"）
    1. 宁可漏拆，不可误拆 —— 所有放宽都必须有"题号递增性"或"选项字母序列"作为证据
    2. 每题必须能一眼看出错误 —— 存疑的题打 warnings，前端可高亮
    3. 原文档格式不可控 —— 规则全部来自统计，不依赖固定模板

核心机制
--------
1) 题号序列推断
   题号天然递增，所以
     * 数字被识别成字母/汉字时，用"前后已知题号之间的空位"反推它
     * 误识别的行（IP 地址、版本号、配置命令）会因为破坏递增性被丢弃
2) 题型标签优先
   【单选题】/【多选题】/【判断题】是最强的题型证据，优先于字母数量推断
3) 选项序列推断
   选项字母天然是 A,B,C,D... 连续，所以
     * 位置优先：按出现顺序依次赋值 A,B,C,D...
     * 检测到的字母若与位置冲突且证据弱，则以位置为准并记 warning
4) 答案识别（多路兜底）
   显式"答案/参考答案"行 > 题干内括号答案 > 独立成行的 "A) 【单选题】" > 题干尾部 "X) 【类型】"
"""
import re

# ====================================================================
# 0. 通用工具
# ====================================================================

_CJK_RE = re.compile(r'[\u4e00-\u9fff]')
_ASCII_ONLY_RE = re.compile(r'^[\x20-\x7e]+$')
# 明显是续行（子项、编号、图表说明）
_RE_CONT_PREFIX = re.compile(r'^\s*(?:[（(]?\d{1,3}[).、．]|[-*•·]|[（(]|[①-⑩])')


_RE_PAGE_MARKER = re.compile(r'^\s*=+\s*page\s+\d+\s*=+\s*$', re.I)

# 调试钩子：模块级变量，被丢弃的题会回调（签名见 parse_ocr_text）
_DROP_HOOK = None


def _clean(s):
    if s is None:
        return ""
    s = s.replace('\u3000', ' ').replace('\xa0', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    return s.strip()


def _is_cjk_doc(text):
    """中文文档判定：CJK 字符占比足够高时启用中文专用规则"""
    if not text:
        return False
    cjk = len(_CJK_RE.findall(text))
    return cjk >= 20 and cjk * 30 >= len(text)


def _is_cjk_text(s):
    return bool(_CJK_RE.search(s or ''))


# ====================================================================
# 1. 题号识别
# ====================================================================

_RE_NUM_SEP = re.compile(r'^(\d{1,3})\s*[.、．\)）]\s*(\S.*)$')          # "1." "2、" "3)"
_RE_NUM_SPACE = re.compile(r'^(\d{1,3})[ ]{1,4}([^\s].*)$')             # "2 某网络工程师"
_RE_NUM_TIGHT = re.compile(r'^(\d{1,3})([\u4e00-\u9fff].*)$')           # "1主机在访问"
_RE_NUM_DASH = re.compile(r'^(\d{1,3})\s*[-—–－]\s*(\S.*)$')           # "16-TFI ospt"
_RE_NUM_COMMA = re.compile(r'^(\d{1,3})\s*[，,]\s*(\S.*)$')             # "54, 管理信息库"
_RE_NUM_ALNUM = re.compile(r'^(\d{1,2})([A-Za-z])\s*[.、．]\s*(\S.*)$')  # "2a.ARiR"
_RE_NUM_ALPHA = re.compile(r'^([A-Za-z\u4e00-\u9fff])\s*[.、．]\s*(\S.*)$')  # "了.OSPF" "S.IEEE"
_RE_NUM_LETTER = re.compile(r'^(\d{1,3})([A-Za-z]{2,8})(?=[\s\u4e00-\u9fff\[（(])')  # "11VRP"

# 数字被识别成字母/汉字时的候选
_DIGIT_CONFUSE = {
    'O': (0,), 'o': (0,), 'Q': (0,), 'D': (0,),
    'l': (1,), 'I': (1,), '|': (1,),
    'Z': (2,), 'z': (2,),
    'S': (5, 9), 's': (5,),
    'G': (6,), 'g': (9,), 'q': (9,),
    '了': (7,), '刀': (7,), '目': (7,), '曰': (7,), '吕': (7,),
    'T': (7,), 't': (7,),
}
_ALPHA_HEAD = set(_DIGIT_CONFUSE) - set('ABCDEFGH')


def _rest_is_question(rest, cjk_doc):
    """排除把 IP / 版本号 / 纯数字列表误判成题号"""
    if not rest:
        return False
    if rest[0].isdigit():
        return False
    if re.match(r'^\d+(?:\.\d+)+', rest):
        return False
    if cjk_doc and not _CJK_RE.search(rest):
        return False
    return True


def _collect_num_candidates(lines, cjk_doc):
    """逐行收集题号候选"""
    cands = []
    for idx, line in enumerate(lines):
        m = _RE_NUM_ALNUM.match(line)
        if m:
            base, letter, rest = int(m.group(1)), m.group(2), m.group(3)
            if _rest_is_question(rest, cjk_doc):
                cands.append({'idx': idx, 'kind': 'alnum', 'num': None, 'base': base,
                              'letter': letter, 'rest': rest, 'conf': 0.5})
                continue

        m = _RE_NUM_ALPHA.match(line)
        if m:
            head, rest = m.group(1), m.group(2)
            if head in _ALPHA_HEAD and _rest_is_question(rest, cjk_doc):
                cands.append({'idx': idx, 'kind': 'alpha', 'num': None, 'base': None,
                              'letter': head, 'rest': rest, 'conf': 0.4})
                continue

        for rx, kind, conf in ((_RE_NUM_SEP, 'sep', 1.0),
                               (_RE_NUM_COMMA, 'comma', 0.85),
                               (_RE_NUM_SPACE, 'space', 0.9),
                               (_RE_NUM_TIGHT, 'tight', 0.85),
                               (_RE_NUM_DASH, 'dash', 0.8),
                               (_RE_NUM_LETTER, 'letter', 0.75)):
            m = rx.match(line)
            if not m:
                continue
            rest = m.group(2)
            # 去掉题号后残留的标点（"5 ,关于..." / "1,题干"）
            rest = rest.lstrip(',，、;；:：')
            if not _rest_is_question(rest, cjk_doc):
                continue
            cands.append({'idx': idx, 'kind': kind, 'num': int(m.group(1)), 'base': None,
                          'letter': None, 'rest': rest, 'conf': conf})
            break
    return cands


def _resolve_numbers(cands):
    """用题号递增性补全被 OCR 打坏的题号，并剔除误识别的行。"""
    if not cands:
        return []

    reliable = [c for c in cands if c['num'] is not None]
    ambiguous = [c for c in cands if c['num'] is None]

    seen = set()
    known = []
    for c in reliable:
        if c['num'] in seen:
            continue
        seen.add(c['num'])
        known.append(c)
    known.sort(key=lambda c: c['idx'])

    def _prev_num(idx):
        v = None
        for c in known:
            if c['idx'] < idx:
                v = c['num']
            else:
                break
        return v

    def _next_num(idx):
        for c in known:
            if c['idx'] > idx:
                return c['num']
        return None

    resolved = []
    for c in ambiguous:
        prev = _prev_num(c['idx'])
        nxt = _next_num(c['idx'])
        options = set()

        if c['kind'] == 'alnum':
            base = c['base']
            for d in _DIGIT_CONFUSE.get(c['letter'], ()):
                options.add(base * 10 + d)
            options.add(base * 10)
            options.add(base * 10 + 10)
        else:
            options.update(_DIGIT_CONFUSE.get(c['letter'], ()))

        # 题号之间的空位可以反推："了." 夹在 6 和 8 中间 => 7
        if prev is not None and nxt is not None and nxt - prev == 2:
            options.add(prev + 1)

        valid = set()
        for v in options:
            if prev is not None and v <= prev:
                continue
            if nxt is not None and v >= nxt:
                continue
            valid.add(v)
        if not valid:
            continue

        if prev is not None and (prev + 1) in valid:
            num = prev + 1
        else:
            num = min(valid)
        c = dict(c)
        c['num'] = num
        c['kind'] = 'resolved'
        resolved.append(c)

    all_c = sorted(reliable + resolved, key=lambda c: c['idx'])

    # 递增性过滤：破坏递增的行一律丢弃（IP 地址、重复题号等）
    out = []
    last = 0
    for c in all_c:
        if c['num'] > last:
            out.append(c)
            last = c['num']
    return out


def _split_blocks(lines, cands):
    """按题号切块"""
    blocks = []
    for i, c in enumerate(cands):
        end = cands[i + 1]['idx'] if i + 1 < len(cands) else len(lines)
        blocks.append({'cand': c, 'lines': lines[c['idx']:end]})
    return blocks


# ====================================================================
# 2. 题型标签
# ====================================================================

_TYPE_WORDS = ('单选题', '多选题', '判断题', '填空题', '简答题', '单选', '多选', '判断',
               '无线考点', '安全考点', '网络考点', 'VLAN考点', '数通考点')

# OCR 把题型标签的字吃了/换了，常见变体：
#   "【判断是】"(判断题)  "【单选是】"  "【单选是}"  "【多选征】"
#   "(多选国"  "(多选重"  "(多选轿"  "(多选辐"  "(多选生"  "(多选彝"  "(多选车"
#   "(多选题}"  "[Sie]"  "[See]"  "[多选]"
# 规则：题干以 "N选/N判" 开头，且括号里出现了被 OCR 破坏的题型词。
_RE_TYPE_OCR = re.compile(
    r'^[\(（\[【]?\s*(单选|多选|判断|填空|简答)[^\)）\]】]{0,3}[\)）\]】]?\s*')
_RE_TYPE_TAG = re.compile(
    r'[【\[（(]\s*(' + '|'.join(_TYPE_WORDS) + r')\s*[题是]?\s*[】\]）)]?')
_RE_TYPE_BARE = re.compile(r'^\s*[（(]?\s*(' + '|'.join(_TYPE_WORDS) + r')\s*[题是]?\s*[】\]）)]?\s*$')

_TYPE_MAP = {
    '单选题': 'single', '单选': 'single',
    '多选题': 'multiple', '多选': 'multiple',
    '判断题': 'judge', '判断': 'judge',
    '填空题': 'blank', '填空': 'blank',
    '简答题': 'short', '简答': 'short',
}


def _detect_type_tag(text):
    """从文本里找题型标签，返回 (type, 命中的原文)"""
    if not text:
        return None, None
    m = _RE_TYPE_TAG.search(text)
    if m:
        return _TYPE_MAP.get(m.group(1)), m.group(0)
    m = _RE_TYPE_BARE.match(text)
    if m:
        return _TYPE_MAP.get(m.group(1)), m.group(0)
    # OCR 把题型标签毁了："(多选国" "【判断是】" "(单选是}"
    m = _RE_TYPE_OCR.match(text.strip())
    if m:
        return _TYPE_MAP.get(m.group(1)), m.group(0)
    return None, None


# ====================================================================
# 3. 选项识别
# ====================================================================

_RE_OPT_STRONG = re.compile(r'^\s*([A-Ha-h])\s*[.、．\)），,：:]\s*(\S.*)$')
_RE_OPT_SPACED = re.compile(r'^\s*([A-Ha-h])\s{1,3}(\S.*)$')
_RE_OPT_TIGHT = re.compile(r'^\s*([A-Ha-h])(\S.*)$')

# OCR 把选项字母 A/B/C/D 认成了形近汉字
_OPT_CJK_CONFUSE = {
    '人': 'A', '斥': 'A', '大': 'A', '个': 'A', '入': 'A',
    '日': 'B', '目': 'B', '曰': 'B', '旦': 'B', '且': 'B', '白': 'B',
    '吕': 'C', '品': 'C',
    '口': 'D', '囗': 'D',
    # OCR 把 "A." / "B." / "C." 认成了版权/圈号/井号
    '®': 'A', 'Ⓐ': 'A',
    '©': 'B', 'Ⓑ': 'B',
    '＠': 'C', '©': 'B',
}

# OCR 把选项字母 D 认成了数字 0 / 字母 O（"D2和11" -> "02和11"）
_RE_OPT_ZERO = re.compile(r'^\s*[0O]\s*[.、．\)），,：:]\s*(\S.*)$')

# 判断题选项正文特征（不加 $，允许 OCR 垃圾后缀，如 "False 如下图所示...")
_RE_JUDGE_OPT = re.compile(r'^(?:[Tt]rue|[Ff]alse|正确|错误|对|错|√|×)')
_RE_CJK_JUDGE = re.compile(r'(正确|错误|对|错)')


def _detect_letter(line):
    """返回 (字母, 证据强度, 正文)；强度 3=有分隔符 2=有空格或形近汉字 1=完全粘连"""
    # 优先判断判断题选项（True/False/正确/错误），避免被 _RE_OPT_TIGHT 误判为字母选项
    if _RE_JUDGE_OPT.match(line):
        t = line.strip()
        up = t.upper()
        if up.startswith(('T', '正确', '对', '√')):
            return 'A', 3, t
        if up.startswith(('F', '错误', '错', '×')):
            return 'B', 3, t
        return None, 0, t
    m = _RE_OPT_STRONG.match(line)
    if m:
        return m.group(1).upper(), 3, m.group(2).strip()
    m = _RE_OPT_SPACED.match(line)
    if m:
        return m.group(1).upper(), 2, m.group(2).strip()
    head = line[:1]
    if head in _OPT_CJK_CONFUSE:
        return _OPT_CJK_CONFUSE[head], 2, line[1:].strip()
    m = _RE_OPT_TIGHT.match(line)
    if m:
        return m.group(1).upper(), 1, m.group(2).strip()
    return None, 0, line.strip()


def _looks_like_numeric(text):
    """正文是不是纯数字/带小数点的数值（用来判断 "0.32768" 是选项 D 还是数值）"""
    t = text.strip()
    if not t:
        return False
    return bool(re.match(r'^[\d,.\s%]+$', t))


def _pick_bracket_answer(stem):
    """
    从题干里挑出"最像答案"的括号内容。

    踩坑记录：题干里可能有多个括号，例如
        "126 如下图所示，下列说法正确的是? (C ) (HIE)"
    最后一个括号是 OCR 噪声。判断依据（从强到弱）：
      1. 括号**闭合**且内容是纯 A-H 字母 -> 强证据
      2. 括号后紧跟题型标签（"【单选题】"）-> 次强证据
      3. 括号内容含非字母（"HIE"）-> 弱证据
    取证据最强的那个。
    """
    best = None
    best_score = -1e9
    for m in _RE_ANS_MARK_CLOSED.finditer(stem):
        raw = re.sub(r'[\s,，、]', '', m.group(1)).upper()
        if not raw or not all(c in 'ABCDEFGH' for c in raw):
            continue
        tail = stem[m.end():m.end() + 12]
        score = 20
        if _RE_TYPE_AFTER_ANS.match(tail):
            score += 15
        score += len(raw)
        score += m.start() / max(1, len(stem))
        if score > best_score:
            best_score = score
            best = raw
    if best is not None:
        return best

    # 退化：括号没闭合，只能看题型标签
    for m in _RE_ANS_MARK.finditer(stem):
        raw = re.sub(r'[ \t]', '', m.group(1)).upper()
        if not raw:
            continue
        tail = stem[m.end():m.end() + 12]
        score = 5
        if _RE_TYPE_AFTER_ANS.match(tail):
            score += 15
        if all(c in 'ABCDEFGH' for c in raw):
            score += 2
        else:
            score -= 5
        score += m.start() / max(1, len(stem))
        if score > best_score:
            best_score = score
            best = raw
    return best


def _is_continuation(line, prev_text):
    """
    判断一个"没有字母开头"的行是不是上一选项的续行。
    规则（按优先级）：
      1. 以编号/符号/括号开头 -> 续行
      2. 纯 ASCII（表格项、MAC 地址、命令）-> 续行
      3. 上一选项很短（像表头）-> 续行
      4. 否则 -> 新选项（原文被 OCR 吃掉了字母）

    例外：上一项和当前项**都是纯数字**时，一定是两个不同的选项
    （"A36864 / B.24576 / C.4096 / 0.32768"），不能合并。
    """
    if not line:
        return True
    # 纯数字对纯数字 -> 一定是两个不同的选项（"A36864 / B.24576 / C.4096 / 0.32768"）
    # 必须放在 _RE_CONT_PREFIX 之前，否则 "0.32768" 会被当成 "0." 编号续行。
    if _looks_like_numeric(prev_text) and _looks_like_numeric(line):
        return False
    if _RE_CONT_PREFIX.match(line):
        return True
    if _ASCII_ONLY_RE.match(line):
        return True
    if prev_text and len(prev_text) <= 12 and not prev_text.endswith(('。', '.', '？', '?')):
        return True
    return False


# 答案行标记：出现在选项区时意味着选项区已结束
_ANSWER_MARKER_RE = re.compile(
    r'^(?:参考答案|正确答案|答案|SEER|ANSWER|参考案|案)\s*[:：]?',
    re.I)


# OCR 会把同一选项行重复输出两次（"文本: 文本" 或两行完全一样）。做轻量去重，
# 避免把重复行误判为多条选项导致字母错位。
def _dedup_option_text(text):
    """把 OCR 重复的选项文本折成一份：'文本: 文本' -> '文本'，'AB AB' -> 'AB'"""
    t = text.strip()
    if not t:
        return t
    # "文本: 文本"（冒号或中文冒号分隔，两边基本一致）
    for sep in (':', '：'):
        if sep in t:
            left, right = t.split(sep, 1)
            left = left.strip(); right = right.strip()
            if left and left == right:
                return left
    # "AB AB"（空白分隔，两半一致）
    parts = t.split()
    if len(parts) == 2 and parts[0] == parts[1] and len(parts[0]) >= 2:
        return parts[0]
    return t


def _parse_option_region(option_lines):
    """
    把选项区解析成选项列表。
    返回 (opts, issues)
      opts: [{'letter': 'A', 'text': '...', 'detected': 'A', 'strength': 3}]
    """
    opts = []
    issues = []
    expected = 0          # 下一个期望的选项下标
    last_detected = None

    for line in option_lines:
        if not line:
            continue
        # 遇到答案行标记，选项区提前结束，防止把 "参考答案: A" 误当成选项
        if _ANSWER_MARKER_RE.match(line):
            break
        letter, strength, text = _detect_letter(line)
        # 把 OCR 重复输出的选项文本折成一份，避免重复行被误判为多条选项
        text = _dedup_option_text(text)
        prev_text = opts[-1]['text'] if opts else ''

        if letter is None:
            # 没有字母：可能是续行，也可能字母被 OCR 吃掉了
            if not opts:
                # 第一条选项行就丢了字母，不能直接跳过——否则整道题的选项会整体丢失。
                # 只要行长度合理，就按位置分配字母（A,B,C,D...）并记 letter_missing。
                if len(text) >= 4 and expected < 8:
                    opts.append({'letter': chr(ord('A') + expected), 'text': text,
                                 'detected': None, 'strength': 0})
                    issues.append('letter_missing')
                    expected += 1
                continue
            if _is_continuation(line, prev_text):
                opts[-1]['text'] = (opts[-1]['text'] + ' ' + text).strip()
            else:
                if expected >= 8:
                    break
                opts.append({'letter': chr(ord('A') + expected), 'text': text,
                             'detected': None, 'strength': 0})
                issues.append('letter_missing')
                expected += 1
            continue

        idx = ord(letter) - ord('A')
        if idx < 0 or idx > 7:
            continue

        if letter == last_detected:
            # 同一字母重复出现，多半是续行内容里又出现了字母
            opts[-1]['text'] = (opts[-1]['text'] + ' ' + text).strip()
            continue

        if idx < expected:
            # 乱序（小编号）-> 当作续行
            if opts:
                opts[-1]['text'] = (opts[-1]['text'] + ' ' + text).strip()
            continue

        if idx > expected:
            issues.append('letter_gap')

        if expected >= 8:
            break
        opts.append({'letter': chr(ord('A') + expected), 'text': text,
                     'detected': letter, 'strength': strength})
        last_detected = letter
        expected += 1

    return opts, issues


def _find_option_start(lines):
    """
    找到选项区的起始行号。

    OCR 的典型破坏：选项字母被吃掉分隔符（"ADD" / "ALSACK" / "ASCE"），
    于是"第一个选项"看起来不像选项，整段选项就少了一项，
    后面所有字母全部错位（答案 D 指向了第 2 项）。

    策略：
      1. 独立成行的答案（"A) 【单选题】"）优先 —— 它本身就是答案行。
      2. 否则找"字母递增序列"作为选项区起点，优先从 'A' 开始
         （A 是选项区的天然锚点）。
      3. 兜底：第一个有分隔符/空格的字母行。
    """
    # 1) 独立成行的答案
    for i in range(1, len(lines)):
        if _RE_STANDALONE_ANS.match(lines[i]):
            return i

    letters = []
    for l in lines:
        L, s, t = _detect_letter(l)
        letters.append((L, s, t))

    def run_len(i):
        """从 i 开始的"字母严格递增"序列长度（跳过无字母行）"""
        n = 0
        last = None
        for j in range(i, len(letters)):
            L = letters[j][0]
            if L is None:
                continue
            if last is None or ord(L) > ord(last):
                n += 1
                last = L
            else:
                break
        return n

    best_a = None
    best_other = None
    for i in range(1, len(lines)):
        L = letters[i][0]
        if L is None:
            continue
        r = run_len(i)
        if r < 2:
            continue
        if L == 'A':
            if best_a is None or r > best_a[1]:
                best_a = (i, r)
        else:
            if best_other is None or r > best_other[1]:
                best_other = (i, r)

    if best_a and (best_other is None or best_a[1] >= best_other[1] - 1):
        return best_a[0]
    if best_other:
        return best_other[0]
    for i in range(1, len(lines)):
        if letters[i][1] >= 2:
            return i
    return len(lines)


def _is_judge_options(opts):
    """判断题特征：选项正文里出现 正确/错误/True/False"""
    if len(opts) != 2:
        return False
    hits = 0
    for o in opts:
        t = o['text'].strip()
        if _RE_JUDGE_OPT.match(t):
            hits += 1
        elif _RE_CJK_JUDGE.search(t):
            hits += 1
    return hits >= 1


# ====================================================================
# 4. 答案识别
# ====================================================================

_RE_ANSWER_LINE = re.compile(
    r'^\s*[#\*]?\s*(?:正确答案|参考答案|答案)\s*[:：]?\s*(.+?)\s*$'
)
# OCR 把"答案/Answer"认成了 "SEER" / "ANSWER" / "参考案"
# 例："SEER: A"  "SEER: C"  "参考答案: ACD"
_RE_ANSWER_LINE_OCR = re.compile(
    r'^\s*[#\*]?\s*(?:SEER|SEER\s*\d*|ANSWER|参考答案|参考案|案)\s*[:：]\s*([A-Ha-h]{1,6})\s*$',
    re.I)
_RE_ANALYSIS_LINE = re.compile(r'^\s*[#\*]?\s*(?:解析|分析|答案解析)\s*[:：]?\s*(.*)$')

# 题干里的括号答案： "(A)" "( C )" "{B)" "(B 】" "(_D)"
_RE_ANS_MARK = re.compile(r'[\(（{]\s*[_~*\-]?\s*([A-Ha-h](?:[ \t]*[A-Ha-h]){0,7})')
# 闭合完整的括号答案： "(C)" "( C )" "(AD)" "(B 】" "{B)"
_RE_ANS_MARK_CLOSED = re.compile(
    r'[\(（{]\s*[_~*\-]?\s*([A-Ha-h][A-Ha-h \t,，、]{0,15}?)\s*[\)）\]】]')
# 紧跟在括号答案后面的题型标签： "(C )【单选题】"
_RE_TYPE_AFTER_ANS = re.compile(
    r'^\s*(?:' + '|'.join(_TYPE_WORDS) + r')\s*[题是]?\s*[】\]）)]?\s*$')
# 独立成行的答案： "A) 【单选题】"
_RE_STANDALONE_ANS = re.compile(
    r'^\s*([A-Ha-h])\s*[\)）]\s*[【\[（(]?\s*(' + '|'.join(_TYPE_WORDS) + r')?\s*[题是]?\s*[】\]）)]?\s*$')
# 题干尾部的 "X) 【单选题】"（没有左括号）
_RE_ANS_TAIL = re.compile(
    r'([A-Ha-h])\s*[\)）]\s*[【\[（(]?\s*(' + '|'.join(_TYPE_WORDS) + r')?\s*[题是]?\s*[】\]）)]?\s*$')
# 答案里的数字误识别： "(8)" 其实是 "(B)"
_ANS_DIGIT_CONFUSE = {'8': 'B', '6': 'G', '1': 'I', '0': 'O', '5': 'S'}


def _normalize_answer(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    s = s.strip('。.；;，,')
    s = s.strip('()（）[]【】{}')
    s = s.strip()
    upper = s.upper()
    if upper in ("正确", "对", "TRUE", "T", "√", "是"):
        return "T"
    if upper in ("错误", "错", "FALSE", "F", "×", "否"):
        return "F"
    parts = [p.strip().upper() for p in re.split(r'[,，、\s]+', s) if p.strip()]
    if len(parts) > 1 and all(len(p) == 1 and p in "ABCDEFGH" for p in parts):
        return parts
    if len(s) > 1 and all(c.upper() in "ABCDEFGH" for c in s):
        return [c.upper() for c in s]
    if len(s) == 1 and s.upper() in "ABCDEFGH":
        return s.upper()
    return s.upper()


def _letters_of(ans):
    if ans is None:
        return []
    if isinstance(ans, list):
        out = []
        for a in ans:
            out.extend([c for c in str(a).upper() if c in 'ABCDEFGH'])
        return out
    return [c for c in str(ans).upper() if c in 'ABCDEFGH']


# ====================================================================
# 5. 单题解析
# ====================================================================

# 题干尾部的"标签"：必须有闭合括号，否则不删。
# 踩坑记录：原来写成 `[\[【（(][^\]】）)]*[\]】）)]?\s*$`（闭合括号可选），
# 于是 "(多选国使能Proxy ARP功能的路由器收到一个ARP请求报文时，发现…"
# 这种**没有闭合括号**的题干会被从 "(" 一直删到句尾，题干整个消失 -> 题目被丢。
_RE_TAIL_TAG = re.compile(r'[\[【（(][^\]】）)\n]{0,60}[\]】）)]\s*$')
# 单独的尾部残渣（没有闭合括号的标签），只在很短且像标签时才删
_RE_TAIL_TAG_SHORT = re.compile(r'[\[【（(][^\]】）)\n]{0,12}$')
_RE_TRAILING_JUNK = re.compile(r'[\s\)\]】、,，]+$')


def _strip_tail_junk(stem):
    """去掉题干尾部的题型标签（"【判断题" "[RN]" "[S280]"）"""
    s = stem.strip()
    prev = None
    while prev != s:
        prev = s
        s2 = _RE_TAIL_TAG.sub('', s).strip()
        if s2 == s:
            break
        s = s2
    # 短残渣（像 "[RN]" 这种），只删长度很短的
    m = _RE_TAIL_TAG_SHORT.search(s)
    if m and m.start() > 0:
        tail = s[m.start():]
        # 只有当剩下的正文仍然够长、且残渣不像句子时才删
        if len(s[:m.start()].strip()) >= 8 and len(tail) <= 14:
            s = s[:m.start()].strip()
    return s


def _parse_block(block, cjk_doc):
    cand = block['cand']
    lines = block['lines']

    # ---------- 独立成行的答案（"A) 【单选题】"） ----------
    standalone_ans = None
    standalone_idx = None
    for i in range(1, len(lines)):
        m = _RE_STANDALONE_ANS.match(lines[i])
        if m and m.group(1):
            standalone_ans = m.group(1).upper()
            standalone_idx = i
            break

    if standalone_idx is not None:
        opt_start = standalone_idx + 1
    else:
        opt_start = _find_option_start(lines)

    option_lines = lines[opt_start:]

    # ---------- 题干 ----------
    stem_lines = [cand['rest']]
    for i in range(1, opt_start):
        line = lines[i]
        if _RE_ANSWER_LINE.match(line) or _RE_ANALYSIS_LINE.match(line):
            continue
        if _RE_ANSWER_LINE_OCR.match(line):
            continue
        if _RE_STANDALONE_ANS.match(line):
            continue
        stem_lines.append(line)

    # ---------- 显式答案 / 解析 ----------
    answer = None
    analysis_lines = []
    for line in lines[1:]:
        if _RE_ANALYSIS_LINE.match(line):
            analysis_lines.append(line)
            continue
        m = _RE_ANSWER_LINE.match(line)
        if m and answer is None:
            answer = _normalize_answer(m.group(1))
            continue
        # OCR 变体："SEER: A" / "ANSWER: A"
        m = _RE_ANSWER_LINE_OCR.match(line)
        if m and (answer is None or not _letters_of(answer)):
            answer = _normalize_answer(m.group(1))

    opts, issues = _parse_option_region(option_lines)
    option_texts = [o['text'] for o in opts]
    opt_letters = [o['letter'] for o in opts]

    # ---------- 题干里的括号答案 ----------
    stem_raw = " ".join(p for p in stem_lines if p).strip()
    if answer is None or not _letters_of(answer):
        raw = _pick_bracket_answer(stem_raw)
        if raw:
            if all(c in 'ABCDEFGH' for c in raw):
                answer = _normalize_answer(raw)
            elif len(raw) == 1 and raw in _ANS_DIGIT_CONFUSE:
                answer = _ANS_DIGIT_CONFUSE[raw]
        if answer is None or not _letters_of(answer):
            # 题干尾部 "X) 【单选题】"
            m = _RE_ANS_TAIL.search(stem_raw)
            if m:
                answer = m.group(1).upper()
        if answer is None or not _letters_of(answer):
            # 括号被拆行："...端口? ("  下一行 "A)"
            m = re.search(r'[\(（]\s*$', stem_raw)
            if m and standalone_ans:
                answer = standalone_ans

    if answer is None and standalone_ans:
        answer = standalone_ans

    # ---------- 清理题干 ----------
    stem = _strip_tail_junk(stem_raw)
    # 去掉末尾的答案括号（绝对位置切片）。只切最后一个标记，
    # 且切完后必须还剩下有意义的题干，否则保留原样。
    marks = list(_RE_ANS_MARK.finditer(stem))
    if marks:
        cut = stem[:marks[-1].start()].rstrip()
        if len(cut) >= 8:
            stem = cut
    stem = _RE_TRAILING_JUNK.sub('', stem).strip()
    stem = re.sub(r'\s+', ' ', stem)

    if not stem or answer is None:
        if _DROP_HOOK is not None:
            _DROP_HOOK(cand, lines, stem_raw, answer, standalone_ans)
        return None

    warnings = list(issues)

    # ---------- 题型 ----------
    tag_type, _tag_raw = _detect_type_tag(stem_raw)
    if tag_type is None:
        tag_type, _ = _detect_type_tag(" ".join(option_lines[:3]))

    letters = _letters_of(answer)
    if tag_type:
        qtype = tag_type
        if qtype == 'judge':
            if letters:
                first = letters[0]
                if first == 'A':
                    answer = "T"
                elif first == 'B':
                    answer = "F"
                else:
                    warnings.append('judge_answer_mismatch')
            elif answer in ("T", "F"):
                pass
            else:
                up = str(answer).upper()
                if up in ("TRUE", "正确", "对"):
                    answer = "T"
                elif up in ("FALSE", "错误", "错"):
                    answer = "F"
                else:
                    return None
        elif qtype == 'single':
            if len(letters) > 1:
                warnings.append('type_conflict')
            if len(letters) == 1:
                answer = letters[0]
        elif qtype == 'multiple':
            if len(letters) == 1:
                warnings.append('type_conflict')
            if len(letters) >= 1:
                answer = letters
    else:
        if _is_judge_options(opts):
            qtype = "judge"
            if letters:
                if letters[0] == 'A':
                    answer = "T"
                elif letters[0] == 'B':
                    answer = "F"
                else:
                    warnings.append('judge_answer_mismatch')
        elif len(letters) > 1:
            qtype = "multiple"
        elif len(letters) == 1:
            qtype = "single"
        else:
            qtype = "judge" if answer in ("T", "F") else "single"

    if qtype == "single" and isinstance(answer, list):
        qtype = "multiple"
    if qtype == "multiple" and isinstance(answer, str) and len(answer) == 1:
        qtype = "single"

    # ---------- 一致性检查 ----------
    if qtype in ("single", "multiple"):
        if not opt_letters:
            warnings.append('options_missing')
        else:
            missing = [l for l in _letters_of(answer) if l not in opt_letters]
            if missing:
                warnings.append('answer_not_in_options')
    if qtype == "judge" and answer not in ("T", "F"):
        return None

    result = {
        "type": qtype,
        "question": stem,
        "options": option_texts,
        "answer": answer,
        "score": 2,
        "analysis": " ".join(l.strip() for l in analysis_lines).strip(),
        "_qnum": cand['num'],
    }
    if warnings:
        result["warnings"] = sorted(set(warnings))
    return result


# ====================================================================
# 6. 入口
# ====================================================================

def parse_ocr_text(text, detail=False):
    """OCR 容错解析。detail=True 时额外返回诊断信息。"""
    lines = [_clean(l) for l in (text or '').split('\n')]
    lines = [l for l in lines if l and not _RE_PAGE_MARKER.match(l)]
    cjk_doc = _is_cjk_doc(text or '')

    cands = _collect_num_candidates(lines, cjk_doc)
    resolved = _resolve_numbers(cands)
    blocks = _split_blocks(lines, resolved)

    questions = []
    for b in blocks:
        q = _parse_block(b, cjk_doc)
        if q:
            q["_raw_text"] = "\n".join(b["lines"])
            questions.append(q)

    if not detail:
        return questions

    diag = {
        "lines": len(lines),
        "cjk_doc": cjk_doc,
        "candidates": len(cands),
        "resolved": len(resolved),
        "blocks": len(blocks),
        "questions": len(questions),
        "with_warnings": sum(1 for q in questions if q.get("warnings")),
    }
    return questions, diag
