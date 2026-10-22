# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parsers_ocr as P

raw = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "tests", "fixtures", "ocr_scan.txt"), encoding="utf-8").read()
lines = [P._clean(l) for l in raw.split("\n")]
lines = [l for l in lines if l]
cjk = P._is_cjk_doc(raw)
cands = P._collect_num_candidates(lines, cjk)
resolved = P._resolve_numbers(cands)
blocks = P._split_blocks(lines, resolved)

out = open("debug_b2.txt", "w", encoding="utf-8")
for b in blocks:
    if b['cand']['num'] not in (2, 3, 8, 22, 39):
        continue
    lines_b = b['lines']
    out.write(f"\n===== block {b['cand']['num']} =====\n")
    oc = P._opt_candidates(lines_b)
    for o in oc:
        out.write(f"  OPT idx={o['idx']} letter={o['letter']} str={o['strength']} text={o['text'][:60]!r}\n")
    ans = None
    for line in lines_b[1:]:
        if P._RE_ANALYSIS_LINE.match(line):
            continue
        m = P._RE_ANSWER_LINE.match(line)
        if m and ans is None:
            ans = P._normalize_answer(m.group(1))
    out.write(f"  explicit answer = {ans!r}\n")
    opts, mode = P._best_option_run(oc, P._letters_of(ans))
    out.write(f"  best run mode={mode} letters={[o['letter'] for o in opts]}\n")
    fo = min(o['idx'] for o in opts) if opts else len(lines_b)
    stem_parts = [b['cand']['rest']] + lines_b[1:min(fo, len(lines_b))]
    stem = " ".join(p for p in stem_parts if p).strip()
    out.write(f"  stem = {stem[:200]!r}\n")
    if ans is None:
        tail = stem[-90:]
        out.write(f"  tail = {tail!r}\n")
        ms = list(P._RE_ANS_MARK.finditer(tail))
        out.write(f"  ans marks = {[m.group(1) for m in ms]}\n")
out.close()
print("ok")
