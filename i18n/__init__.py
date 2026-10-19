# -*- coding: utf-8 -*-
"""智卷多语言支持"""
import json
import os
from flask import session, request

I18N_DIR = os.path.dirname(os.path.abspath(__file__))
SUPPORTED = ["zh_CN", "en_US", "ja_JP"]
DEFAULT = "zh_CN"
LANG_LABELS = {
    "zh_CN": "中文",
    "en_US": "EN",
    "ja_JP": "日本語",
}
# 浏览器 / HTML 用的 BCP-47 标签，与内部文件名（下划线）区分开
LANG_TAGS = {
    "zh_CN": "zh-CN",
    "en_US": "en-US",
    "ja_JP": "ja-JP",
}
_cache = {}


def _load(lang):
    if lang in _cache:
        return _cache[lang]
    path = os.path.join(I18N_DIR, f"{lang}.json")
    if not os.path.exists(path):
        lang = DEFAULT
        path = os.path.join(I18N_DIR, f"{lang}.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _cache[lang] = data
    return data


def get_lang():
    lang = request.args.get("lang")
    if lang and lang in SUPPORTED:
        session["lang"] = lang
        return lang
    if "lang" in session and session["lang"] in SUPPORTED:
        return session["lang"]
    browser = request.accept_languages.best_match(SUPPORTED)
    return browser or DEFAULT


def t(key, **kwargs):
    """支持传入变量替换占位符，例如 t('home.bank_size', n=10)

    查表顺序：当前语言 -> 默认语言(zh_CN) -> key 本身。
    缺键时回退到中文并打印告警，避免界面上直接显示 "convert.xxx" 这种裸键。
    注意：模板里请直接用 t('x')，不要再写 |default('中文')——Jinja 的 default
    只对 Undefined 生效，对 t() 返回的字符串永远不生效，属于死代码。
    """
    try:
        lang = get_lang()
    except Exception:
        lang = DEFAULT

    data = _load(lang)
    template = data.get(key)
    if template is None:
        template = _load(DEFAULT).get(key)
        if template is None:
            print(f"[i18n] missing key: {key} (lang={lang})")
            template = key
        else:
            print(f"[i18n] key '{key}' missing in {lang}, fallback to {DEFAULT}")

    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template

    return template


def register(app):
    @app.context_processor
    def inject_i18n():
        lang = get_lang()
        return {
            "t": t,
            "current_lang": lang,
            "lang_tag": LANG_TAGS.get(lang, "zh-CN"),
            "supported_langs": SUPPORTED,
            "lang_labels": LANG_LABELS,
        }