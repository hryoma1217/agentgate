# -*- coding: utf-8 -*-
"""test_unicode_falsepos.py -- False-positive gate for unicode_safety check.

All fixtures here MUST produce zero issues under default policy.
Non-ASCII characters are written as LITERAL UTF-8 in this file.

Covers:
  - Arabic text with ZWNJ (U+200C) -- legitimate in Arabic morphology
  - Persian text with ZWNJ -- legitimate in Persian typography
  - Hindi text with ZWJ (U+200D) -- legitimate in Devanagari conjuncts
  - Emoji ZWJ sequences (e.g. family emoji)
  - BOM at offset 0 of file content (benign)
  - Ordinary Markdown prose
  - Legitimate CJK text in prose
  - LRM/RLM (U+200E/U+200F) in Arabic/bilingual text
"""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from agentgate.checks.unicode_safety import run
from agentgate.config import GateConfig
from agentgate.model import WriteEvent


def _make_event(content: str, file_path: str = "README.md") -> WriteEvent:
    return WriteEvent(
        agent="generic",
        phase="unknown",
        tool="unknown",
        file_path=file_path,
        content=content,
    )


class TestArabicPersianClean(unittest.TestCase):
    """Arabic and Persian text with ZWNJ must not trigger false positives."""

    def test_arabic_text_with_zwnj(self):
        # Arabic word "می‌خواهم" uses ZWNJ (U+200C) between morphemes
        # This is standard Persian typography
        content = "می\u200cخواهم که بروم"
        issues = run(_make_event(content), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_persian_text_with_zwnj(self):
        # Persian: "نمی‌توانم" -- cannot
        content = "نمی\u200cتوانم این کار را بکنم"
        issues = run(_make_event(content), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_arabic_with_lrm(self):
        # U+200E LEFT-TO-RIGHT MARK used in bidirectional text
        content = "Hello \u200e مرحبا world"
        issues = run(_make_event(content), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_arabic_with_rlm(self):
        # U+200F RIGHT-TO-LEFT MARK
        content = "English text \u200f ثم عربي"
        issues = run(_make_event(content), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_arabic_prose_document(self):
        # Full Arabic paragraph
        content = """هذا مستند عربي عادي.
يحتوي على نصوص متعددة الأسطر.
وهو سليم تماماً."""
        issues = run(_make_event(content, "arabic.md"), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")


class TestHindiDevanagariClean(unittest.TestCase):
    """Hindi/Devanagari text with ZWJ must not trigger false positives."""

    def test_hindi_with_zwj(self):
        # Hindi uses ZWJ (U+200D) for certain conjunct consonants
        # "क्‍ष" -- ZWJ-based conjunct
        content = "क्\u200dष वर्ण"
        issues = run(_make_event(content), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_hindi_prose(self):
        # Plain Hindi paragraph
        content = """यह एक हिंदी दस्तावेज़ है।
इसमें कई पंक्तियाँ हैं।
सब कुछ ठीक है।"""
        issues = run(_make_event(content, "hindi.md"), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_devanagari_zwnj(self):
        # ZWNJ used between Devanagari half-consonants
        content = "प्र\u200cयोग"
        issues = run(_make_event(content), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")


class TestEmojiZWJSequences(unittest.TestCase):
    """Emoji ZWJ sequences must not trigger false positives."""

    def test_family_emoji(self):
        # 👨‍👩‍👧‍👦 family emoji uses ZWJ (U+200D) sequences
        content = "Our team 👨\u200d👩\u200d👧\u200d👦 is great"
        issues = run(_make_event(content), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_flag_sequences(self):
        # Various emoji in prose
        content = "We support 🌍 global teams and use 🔧 tools."
        issues = run(_make_event(content), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_person_profession_emoji(self):
        # 👩‍💻 woman technologist -- ZWJ sequence
        content = "The developer 👩\u200d💻 wrote the code."
        issues = run(_make_event(content), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_zwj_in_emoji_not_flagged_in_code(self):
        # Even in a .py file, ZWJ in emoji context should not trigger
        # (ZWJ between emoji codepoints is not an ASCII-identifier context)
        content = '# Comment with emoji 👨\u200d💻\nprint("hello")'
        issues = run(_make_event(content, "app.py"), GateConfig())
        invis = [i for i in issues if i.rule_id == "AG-INVIS"]
        self.assertEqual(invis, [], f"Unexpected AG-INVIS: {invis}")


class TestBOMAtOffset0(unittest.TestCase):
    """BOM at the very start of content (offset 0) must be ignored."""

    def test_bom_at_start_clean(self):
        # U+FEFF at offset 0 is the BOM, not a stray invisible char
        content = chr(0xFEFF) + "normal content here"
        issues = run(_make_event(content, "app.py"), GateConfig())
        invis = [i for i in issues if i.rule_id == "AG-INVIS"]
        self.assertEqual(invis, [], f"BOM at offset 0 should not be flagged: {invis}")

    def test_bom_at_start_doc_file(self):
        content = chr(0xFEFF) + "# README\n\nThis is documentation."
        issues = run(_make_event(content, "README.md"), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")


class TestMarkdownProse(unittest.TestCase):
    """Ordinary Markdown prose must produce zero issues under default policy."""

    def test_english_markdown(self):
        content = """# Project Title

This is a **bold** statement and _italic_ text.

## Features

- Feature one
- Feature two
- Feature three

```python
def hello():
    print("world")
```
"""
        issues = run(_make_event(content, "README.md"), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues in plain markdown: {issues}")

    def test_multilingual_markdown(self):
        content = """# 多言語ドキュメント

This document contains Japanese: 日本語テキスト。
And Korean: 한국어 텍스트.
And Chinese: 中文文本。
And Arabic: نص عربي.
And Hindi: हिंदी पाठ।
"""
        issues = run(_make_event(content, "MULTILINGUAL.md"), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")


class TestLegitCJKText(unittest.TestCase):
    """Legitimate CJK text in prose files must be clean."""

    def test_japanese_prose(self):
        content = """これは日本語のテキストです。
漢字とひらがなとカタカナが含まれています。
プログラミングは楽しいです。"""
        issues = run(_make_event(content, "README.md"), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_chinese_prose(self):
        content = """这是中文文本。
包含汉字和标点符号。
人工智能很有趣。"""
        issues = run(_make_event(content, "readme.md"), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")

    def test_korean_prose(self):
        content = """이것은 한국어 텍스트입니다.
한글과 한자가 포함되어 있습니다.
프로그래밍은 재미있습니다."""
        issues = run(_make_event(content, "README.md"), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues: {issues}")


class TestCodeFileClean(unittest.TestCase):
    """Clean Python source must produce zero issues."""

    def test_clean_python(self):
        content = '''#!/usr/bin/env python3
"""Module docstring."""

from __future__ import annotations

import os
import sys


def compute(value: int) -> int:
    """Return the doubled value."""
    return value * 2


class MyClass:
    """A simple class."""

    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self) -> str:
        return f"Hello, {self.name}!"


if __name__ == "__main__":
    obj = MyClass("world")
    print(obj.greet())
'''
        issues = run(_make_event(content, "main.py"), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues in clean Python: {issues}")

    def test_clean_javascript(self):
        content = '''// JavaScript module
"use strict";

const API_URL = "https://api.example.com/v1";

async function fetchData(endpoint) {
    const response = await fetch(`${API_URL}/${endpoint}`);
    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json();
}

module.exports = { fetchData };
'''
        issues = run(_make_event(content, "api.js"), GateConfig())
        self.assertEqual(issues, [], f"Unexpected issues in clean JS: {issues}")


if __name__ == "__main__":
    unittest.main()
