"""test_unicode_check.py -- Positive tests for unicode_safety check.

Tests that bidi controls and in-code invisible chars ARE flagged at the
correct line and column.
"""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from agentgate.checks.unicode_safety import run
from agentgate.config import GateConfig, UnicodeConfig
from agentgate.model import WriteEvent


def _make_event(content: str, file_path: str = "test.py") -> WriteEvent:
    return WriteEvent(
        agent="generic",
        phase="unknown",
        tool="unknown",
        file_path=file_path,
        content=content,
    )


def _make_cfg(**unicode_kwargs) -> GateConfig:
    cfg = GateConfig()
    for k, v in unicode_kwargs.items():
        setattr(cfg.unicode, k, v)
    return cfg


class TestBidiControls(unittest.TestCase):
    """AG-BIDI: always flagged, regardless of file type."""

    def test_rtl_override_in_code(self):
        # U+202E RIGHT-TO-LEFT OVERRIDE
        content = "x = " + chr(0x202E) + "dangerous"
        issues = run(_make_event(content, "app.py"), _make_cfg())
        bidi = [i for i in issues if i.rule_id == "AG-BIDI"]
        self.assertEqual(len(bidi), 1)
        self.assertEqual(bidi[0].line, 1)
        self.assertEqual(bidi[0].col, 5)  # 1-indexed, after "x = "
        self.assertIn("202E", bidi[0].message)
        self.assertIn("RIGHT-TO-LEFT OVERRIDE", bidi[0].message)
        self.assertEqual(bidi[0].severity, "high")

    def test_ltr_embedding(self):
        # U+202A
        content = chr(0x202A) + "text"
        issues = run(_make_event(content), _make_cfg())
        bidi = [i for i in issues if i.rule_id == "AG-BIDI"]
        self.assertEqual(len(bidi), 1)
        self.assertIn("202A", bidi[0].message)

    def test_isolate_chars(self):
        # U+2066-U+2069
        for cp in range(0x2066, 0x206A):
            content = f"line{chr(cp)}here"
            issues = run(_make_event(content), _make_cfg())
            bidi = [i for i in issues if i.rule_id == "AG-BIDI"]
            self.assertGreaterEqual(len(bidi), 1, f"U+{cp:04X} not flagged")

    def test_bidi_in_markdown_still_flagged(self):
        # Even in doc files, bidi is always flagged
        content = "Normal text " + chr(0x202E) + " more text"
        issues = run(_make_event(content, "README.md"), _make_cfg())
        bidi = [i for i in issues if i.rule_id == "AG-BIDI"]
        self.assertEqual(len(bidi), 1)

    def test_correct_column_multichar(self):
        # 5 chars before the bidi control
        content = "abcde" + chr(0x202E) + "fg"
        issues = run(_make_event(content), _make_cfg())
        bidi = [i for i in issues if i.rule_id == "AG-BIDI"]
        self.assertEqual(len(bidi), 1)
        self.assertEqual(bidi[0].col, 6)  # 1-indexed

    def test_multiple_bidi_chars(self):
        content = chr(0x202A) + "a" + chr(0x202E) + "b"
        issues = run(_make_event(content), _make_cfg())
        bidi = [i for i in issues if i.rule_id == "AG-BIDI"]
        self.assertEqual(len(bidi), 2)

    def test_bidi_on_second_line(self):
        content = "first line\nsecond " + chr(0x202E) + " line"
        issues = run(_make_event(content), _make_cfg())
        bidi = [i for i in issues if i.rule_id == "AG-BIDI"]
        self.assertEqual(len(bidi), 1)
        self.assertEqual(bidi[0].line, 2)
        self.assertEqual(bidi[0].col, 8)  # "second " = 7 chars + 1-indexed


class TestInvisibleChars(unittest.TestCase):
    """AG-INVIS: flagged only in code context, inside identifier/string."""

    def test_zero_width_space_in_identifier(self):
        # U+200B inside identifier: `foo` + ZWS + `bar`
        content = "x = foo" + chr(0x200B) + "bar"
        issues = run(_make_event(content, "test.py"), _make_cfg())
        invis = [i for i in issues if i.rule_id == "AG-INVIS"]
        self.assertEqual(len(invis), 1)
        self.assertIn("200B", invis[0].message)
        self.assertEqual(invis[0].severity, "high")

    def test_word_joiner_in_string(self):
        # U+2060 inside a string literal
        content = 'name = "hello' + chr(0x2060) + 'world"'
        issues = run(_make_event(content, "app.py"), _make_cfg())
        invis = [i for i in issues if i.rule_id == "AG-INVIS"]
        self.assertEqual(len(invis), 1)
        self.assertIn("2060", invis[0].message)

    def test_soft_hyphen_in_code(self):
        # U+00AD soft hyphen
        content = "def my" + chr(0x00AD) + "func():"
        issues = run(_make_event(content, "x.py"), _make_cfg())
        invis = [i for i in issues if i.rule_id == "AG-INVIS"]
        self.assertEqual(len(invis), 1)
        self.assertIn("00AD", invis[0].message)

    def test_stray_bom_in_identifier(self):
        # U+FEFF NOT at offset 0 (stray BOM in middle of content)
        content = "line1\nfoo" + chr(0xFEFF) + "bar"
        issues = run(_make_event(content, "app.py"), _make_cfg())
        invis = [i for i in issues if i.rule_id == "AG-INVIS"]
        self.assertEqual(len(invis), 1)
        self.assertIn("FEFF", invis[0].message)

    def test_invis_not_flagged_in_doc_context(self):
        # Same char in a .md file -- doc profile, AG-INVIS off
        content = "Some text with" + chr(0x200B) + " zero-width space"
        issues = run(_make_event(content, "README.md"), _make_cfg())
        invis = [i for i in issues if i.rule_id == "AG-INVIS"]
        self.assertEqual(len(invis), 0)

    def test_invis_not_flagged_in_whitespace_context(self):
        # U+200B between two spaces -- not in identifier run
        content = "word " + chr(0x200B) + " word"
        issues = run(_make_event(content, "app.py"), _make_cfg())
        invis = [i for i in issues if i.rule_id == "AG-INVIS"]
        self.assertEqual(len(invis), 0)


class TestHomoglyph(unittest.TestCase):
    """AG-HOMO: opt-in, medium severity."""

    def test_cyrillic_in_ascii_identifier(self):
        # Cyrillic 'а' (U+0430) looks like Latin 'a'
        # Build identifier: "foo" + Cyrillic_a + "r"
        content = "foo" + chr(0x0430) + "r = 1"
        cfg = _make_cfg(homoglyph=True)
        issues = run(_make_event(content, "app.py"), cfg)
        homo = [i for i in issues if i.rule_id == "AG-HOMO"]
        self.assertEqual(len(homo), 1)
        self.assertEqual(homo[0].severity, "medium")

    def test_greek_in_ascii_identifier(self):
        # Greek 'ο' (U+03BF) looks like 'o'
        content = "c" + chr(0x03BF) + "nfig = {}"
        cfg = _make_cfg(homoglyph=True)
        issues = run(_make_event(content, "test.py"), cfg)
        homo = [i for i in issues if i.rule_id == "AG-HOMO"]
        self.assertEqual(len(homo), 1)

    def test_homo_off_by_default(self):
        content = "foo" + chr(0x0430) + "r = 1"
        cfg = GateConfig()  # defaults: homoglyph=False
        issues = run(_make_event(content, "app.py"), cfg)
        homo = [i for i in issues if i.rule_id == "AG-HOMO"]
        self.assertEqual(len(homo), 0)


class TestStrictZerowidth(unittest.TestCase):
    """strict_zerowidth: ZWNJ/ZWJ inside ASCII identifier runs flagged."""

    def test_zwnj_in_ascii_identifier_strict(self):
        # U+200C ZERO WIDTH NON-JOINER in ASCII identifier
        content = "foo" + chr(0x200C) + "bar = 1"
        cfg = _make_cfg(strict_zerowidth=True)
        issues = run(_make_event(content, "app.py"), cfg)
        invis = [i for i in issues if i.rule_id == "AG-INVIS"]
        self.assertEqual(len(invis), 1)

    def test_zwnj_not_flagged_by_default(self):
        content = "foo" + chr(0x200C) + "bar = 1"
        cfg = GateConfig()  # strict_zerowidth=False
        issues = run(_make_event(content, "app.py"), cfg)
        invis = [i for i in issues if i.rule_id == "AG-INVIS"]
        self.assertEqual(len(invis), 0)


if __name__ == "__main__":
    unittest.main()
