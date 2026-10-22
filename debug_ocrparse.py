# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import parsers_ocr as P

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures")
raw = open(os.path.join(FIX, "ocr_scan.txt"), encoding="utf-8").read()

lines = [P._clean(l) for l in raw.split("\n")]
lines = [l for l in lines if l]
cjk = P._is_cjk_doc(raw)

cands = P._collect_num_candidates(lines, cjk)
resolved = P._resolve_numbers(cands)
blocks = P._split_blocks(lines, resolved)

out = open("debug_blocks.txt", "w", encoding="utf-8")
out.write(f"cjk={cjk} lines={len(lines)} cands={len(cands)} resolved={len(resolved)} blocks={len(blocks)}\n\n")
out.write("=== resolved candidates ===\n")
for c in resolved:
    out.write(f"  idx={c['idx']:4d} num={c['num']:4d} kind={c['kind']:9s} rest={c['rest'][:70]!r}\n")

out.write("\n=== block outcomes ===\n")
for b in blocks:
    q = P._parse_block(b, cjk)
    out.write(f"\n--- block num={b['cand']['num']} idx={b['cand']['idx']} ---\n")
    for l in b['lines'][:14]:
        out.write(f"    | {l}\n")
    if q:
        out.write(f"    => OK {q['type']} ans={q['answer']!r} opts={q['options']}\n")
    else:
        out.write("    => DROP\n")
out.close()
print("written debug_blocks.txt")
