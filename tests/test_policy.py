"""test_policy.py -- Tests for policy.py severity->action, suppression, and bidi lock."""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from agentgate.config import GateConfig, PolicyConfig
from agentgate.model import Issue
from agentgate.policy import apply_suppression, decide_block, filter_actionable


def _issue(rule_id="AG-BIDI", severity="high", line=1, check="unicode"):
    return Issue(
        check=check,
        rule_id=rule_id,
        severity=severity,
        line=line,
        col=1,
        message="test message",
        excerpt="x",
    )


class TestSeverityToAction(unittest.TestCase):

    def test_high_blocks(self):
        cfg = GateConfig()
        self.assertTrue(decide_block([_issue(severity="high")], cfg))

    def test_medium_warns_not_blocks(self):
        cfg = GateConfig()
        issue = _issue(rule_id="AG-HOMO", severity="medium")
        self.assertFalse(decide_block([issue], cfg))

    def test_low_ignored(self):
        cfg = GateConfig()
        issue = _issue(severity="low")
        self.assertFalse(decide_block([issue], cfg))

    def test_filter_actionable_removes_low(self):
        cfg = GateConfig()
        issues = [
            _issue(severity="high"),
            _issue(severity="low"),
            _issue(severity="medium"),
        ]
        actionable = filter_actionable(issues, cfg)
        self.assertEqual(len(actionable), 2)
        severities = {i.severity for i in actionable}
        self.assertNotIn("low", severities)

    def test_custom_policy_medium_blocks(self):
        cfg = GateConfig()
        cfg.policy.medium = "block"
        issue = _issue(rule_id="AG-HOMO", severity="medium")
        self.assertTrue(decide_block([issue], cfg))

    def test_empty_issues_allow(self):
        cfg = GateConfig()
        self.assertFalse(decide_block([], cfg))


class TestRuleSpecificSuppression(unittest.TestCase):

    def test_suppression_works_for_ag_invis(self):
        content = "foo" + chr(0x200B) + "bar  # agentgate: ignore[AG-INVIS]"
        issue = _issue(rule_id="AG-INVIS", severity="high", line=1)
        cfg = GateConfig()
        surviving = apply_suppression([issue], content, cfg)
        self.assertEqual(surviving, [])

    def test_suppression_does_not_silence_other_rule(self):
        content = "foo  # agentgate: ignore[AG-INVIS]"
        issue = _issue(rule_id="AG-BIDI", severity="high", line=1)
        cfg = GateConfig()
        surviving = apply_suppression([issue], content, cfg)
        self.assertEqual(len(surviving), 1)

    def test_suppression_multiple_rules(self):
        content = "foo  # agentgate: ignore[AG-INVIS,AG-HOMO]"
        issues = [
            _issue(rule_id="AG-INVIS", line=1),
            _issue(rule_id="AG-HOMO", line=1),
            _issue(rule_id="AG-BIDI", line=1),
        ]
        cfg = GateConfig()
        surviving = apply_suppression(issues, content, cfg)
        # AG-BIDI survives (not suppressible by default), INVIS and HOMO suppressed
        rule_ids = {i.rule_id for i in surviving}
        self.assertIn("AG-BIDI", rule_ids)
        self.assertNotIn("AG-INVIS", rule_ids)
        self.assertNotIn("AG-HOMO", rule_ids)

    def test_no_bare_ignore(self):
        # Bare `agentgate: ignore` (without [RULE]) must NOT suppress anything
        content = "foo  # agentgate: ignore"
        issue = _issue(rule_id="AG-INVIS", severity="high", line=1)
        cfg = GateConfig()
        surviving = apply_suppression([issue], content, cfg)
        # Bare ignore has no effect -- issue should survive
        self.assertEqual(len(surviving), 1)

    def test_suppression_only_on_matching_line(self):
        content = "line1  # agentgate: ignore[AG-INVIS]\nline2"
        issues = [
            _issue(rule_id="AG-INVIS", line=1),
            _issue(rule_id="AG-INVIS", line=2),
        ]
        cfg = GateConfig()
        surviving = apply_suppression(issues, content, cfg)
        # Line 1 suppressed, line 2 survives
        lines = {i.line for i in surviving}
        self.assertIn(2, lines)
        self.assertNotIn(1, lines)


class TestBidiNotSuppressible(unittest.TestCase):

    def test_ag_bidi_not_silenced_by_default(self):
        content = chr(0x202E) + "text  # agentgate: ignore[AG-BIDI]"
        issue = _issue(rule_id="AG-BIDI", severity="high", line=1)
        cfg = GateConfig()
        surviving = apply_suppression([issue], content, cfg)
        # Should NOT be suppressed (allow_bidi_suppression=False by default)
        self.assertEqual(len(surviving), 1)

    def test_ag_bidi_suppressible_when_explicitly_allowed(self):
        content = chr(0x202E) + "text  # agentgate: ignore[AG-BIDI]"
        issue = _issue(rule_id="AG-BIDI", severity="high", line=1)
        cfg = GateConfig()
        cfg.unicode.allow_bidi_suppression = True
        surviving = apply_suppression([issue], content, cfg)
        self.assertEqual(len(surviving), 0)


if __name__ == "__main__":
    unittest.main()
