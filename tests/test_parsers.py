# -*- coding: utf-8 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers import parse_question_text


def test_basic_single_choice():
    text = """
1、以下哪个是 Python 的 Web 框架？
A. Django
B. Flask
C. Java
D. Spring
正确答案：B
"""
    qs = parse_question_text(text)
    assert len(qs) == 1
    assert qs[0]["type"] == "single"
    assert qs[0]["answer"] == "B"
    assert len(qs[0]["options"]) == 4


def test_inline_options():
    text = """
1、以下哪个是 Python 的 Web 框架？
A.Django B.Flask C.Java D.Spring
答案：B
"""
    qs = parse_question_text(text)
    assert len(qs) == 1
    assert len(qs[0]["options"]) == 4


def test_judge():
    text = """
1、Flask 是一个轻量级 Web 框架。
正确
错误
答案：正确
"""
    qs = parse_question_text(text)
    assert len(qs) == 1
    assert qs[0]["type"] == "judge"
    assert qs[0]["answer"] == "T"


def test_trailing_answer():
    text = """
1、以下哪个是 Python 的 Web 框架？（B）
A.Django B.Flask C.Java D.Spring
"""
    qs = parse_question_text(text)
    assert len(qs) == 1
    assert qs[0]["answer"] == "B"


if __name__ == "__main__":
    test_basic_single_choice()
    test_inline_options()
    test_judge()
    test_trailing_answer()
    print("all parser tests passed")