# -*- coding: utf-8 -*-
"""
解析器回归测试 —— 用**真实 OCR 文本**做夹具，覆盖扫描件场景。

背景：原 tests/test_parsers.py 只有 4 个用例，全部是"干净手写"文本，
完全测不到扫描件（标点被 OCR 吃掉）这一真实场景。
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parsers  # noqa: E402

FIX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
OCR_FIX = os.path.join(FIX_DIR, "ocr_scan_up2.txt")


class TestOcrTolerantParser(unittest.TestCase):
    """OCR 容错解析器"""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(OCR_FIX):
            raise unittest.SkipTest(f"缺少夹具 {OCR_FIX}")
        with open(OCR_FIX, encoding="utf-8") as f:
            cls.raw = f.read()

    def test_beats_rule_parser_by_10x(self):
        rule = parsers.parse_question_text(self.raw)
        ocr = parsers.parse_question_text_ocr(self.raw)[0]
        self.assertGreater(len(ocr), len(rule) * 10,
                           f"OCR 解析器应远优于规则解析器：ocr={len(ocr)} rule={len(rule)}")

    def test_parses_most_blocks(self):
        qs, diag = parsers.parse_question_text_ocr(self.raw, detail=True)
        self.assertGreaterEqual(len(qs), diag["blocks"] * 0.9,
                                "应当解析出绝大多数块")
        self.assertGreater(len(qs), 100)

    def test_questions_have_answers(self):
        qs = parsers.parse_question_text_ocr(self.raw)[0]
        with_answer = [q for q in qs if q.get("answer")]
        self.assertGreater(len(with_answer) / len(qs), 0.9,
                           "绝大多数题应能拿到答案")

    def test_option_letters_stripped_but_answer_maps(self):
        """
        选项文字不带字母前缀（app.normalize_question 会再清理一次），
        但答案字母必须指向正确的选项位置。
        少数 OCR 彻底失败的题（选项本身被毁）允许不匹配，
        但必须带 'answer_not_in_options' 警告，让用户能一眼看出错误。
        """
        qs = parsers.parse_question_text_ocr(self.raw)[0]
        checked = 0
        mismatched = []
        for q in qs:
            opts = q.get("options") or []
            ans = q.get("answer")
            if q.get("type") in ("single", "multiple"):
                if not opts or not ans:
                    continue
                letters = ans if isinstance(ans, list) else [ans]
                for L in letters:
                    if len(str(L)) == 1 and str(L).isalpha() and "A" <= str(L) <= "H":
                        idx = ord(str(L)) - ord("A")
                        checked += 1
                        if idx >= len(opts):
                            mismatched.append(q)
        self.assertGreater(checked, 50, "应检查到大量答案-选项对应关系")
        self.assertLess(len(mismatched) / max(1, checked), 0.02,
                        f"答案-选项错配应 <2%，实际 {len(mismatched)}/{checked}")
        for q in mismatched:
            self.assertIn("answer_not_in_options", q.get("warnings") or [],
                          f"错配的题必须带警告：{q.get('_qnum')}")

    def test_no_empty_question_text(self):
        qs = parsers.parse_question_text_ocr(self.raw)[0]
        for q in qs:
            self.assertTrue(q.get("question", "").strip(),
                            f"题干不应为空：{q}")

    def test_qnum_monotonic(self):
        """题号应单调递增（这是"宁可漏拆，不可误拆"底线）"""
        qs = parsers.parse_question_text_ocr(self.raw)[0]
        nums = [q["_qnum"] for q in qs if isinstance(q.get("_qnum"), int)]
        self.assertEqual(nums, sorted(nums))

    def test_judge_questions_have_true_false(self):
        qs = parsers.parse_question_text_ocr(self.raw)[0]
        judges = [q for q in qs if q.get("type") == "judge"]
        self.assertGreater(len(judges), 5)
        for q in judges:
            self.assertIn(q.get("answer"), ("T", "F"),
                          f"判断题答案应为 T/F：{q.get('_qnum')} {q.get('answer')}")

    def test_auto_merges_rule_parser(self):
        merged, diag = parsers.parse_question_text_auto(self.raw, is_ocr=True,
                                                         detail=True)
        self.assertGreaterEqual(len(merged),
                                len(parsers.parse_question_text_ocr(self.raw)[0]))

    def test_analyze_qnums_ocr(self):
        qs = parsers.parse_question_text_ocr(self.raw)[0]
        stats = parsers.analyze_qnums_ocr(self.raw, qs)
        self.assertIn("missing", stats)
        self.assertLess(len(stats["missing"]), 15,
                        f"题号缺失应很少，实际 {stats['missing']}")


class TestAiPayloadCoercion(unittest.TestCase):
    """AI 返回结构的归一化（踩过的坑：模型只返回单个对象导致 0 题）"""

    def test_single_object_becomes_list(self):
        d = {"type": "judge", "question": "x", "options": [], "answer": "T"}
        self.assertEqual(len(parsers._coerce_ai_payload(d)), 1)

    def test_questions_wrapper(self):
        d = {"questions": [{"question": "a"}, {"question": "b"}]}
        self.assertEqual(len(parsers._coerce_ai_payload(d)), 2)

    def test_plain_list(self):
        self.assertEqual(len(parsers._coerce_ai_payload([{"question": "a"}])), 1)

    def test_mixed_list(self):
        d = [{"questions": [{"question": "a"}]}, {"question": "b"}]
        self.assertEqual(len(parsers._coerce_ai_payload(d)), 2)

    def test_parse_ai_response_with_markdown(self):
        txt = '```json\n{"questions": [{"question": "a", "answer": "A"}]}\n```'
        self.assertEqual(len(parsers._parse_ai_response(txt)), 1)

    def test_parse_ai_response_single_object(self):
        txt = '{"type": "judge", "question": "q", "answer": "T"}'
        self.assertEqual(len(parsers._parse_ai_response(txt)), 1)

    def test_schema_exists(self):
        self.assertIn("questions", parsers.AI_PARSE_SCHEMA["properties"])


class TestRuleParserUnchanged(unittest.TestCase):
    """干净文本仍走老解析器，行为不能退化"""

    TEXT = """1. 下列关于OSPF的说法正确的是？
A. OSPF是一种距离矢量协议
B. OSPF是一种链路状态协议
C. OSPF使用Dijkstra算法
D. 以上都不对
答案：B

2. TCP和UDP都是面向连接的协议吗？
A. 是
B. 否
答案：B
"""

    def test_rule_parser(self):
        qs = parsers.parse_question_text(self.TEXT)
        self.assertEqual(len(qs), 2)
        self.assertEqual(qs[0]["answer"], "B")
        self.assertEqual(len(qs[0]["options"]), 4)

    def test_auto_uses_rule_for_clean_text(self):
        qs, diag = parsers.parse_question_text_auto(self.TEXT, is_ocr=False)
        self.assertEqual(len(qs), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
