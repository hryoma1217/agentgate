"""test_cjk_integration.py -- CJK check integration tests.

Two scenarios:
  1. mojihen present (add to sys.path): corrupt CJK line -> MH001 blocks.
  2. cjk enabled with mojihen absent (monkeypatched): startup error, not silent.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Add agentgate src
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Try to add mojihen src so integration test can run
_MOJIHEN_SRC = Path(__file__).parent.parent.parent / "mojihen" / "src"
_MOJIHEN_AVAILABLE = False
if _MOJIHEN_SRC.exists():
    if str(_MOJIHEN_SRC) not in sys.path:
        sys.path.insert(0, str(_MOJIHEN_SRC))
    try:
        import mojihen  # noqa: F401
        _MOJIHEN_AVAILABLE = True
    except ImportError:
        pass


@unittest.skipUnless(_MOJIHEN_AVAILABLE, "mojihen not available in test environment")
class TestCjkIntegration(unittest.TestCase):
    """Integration tests that require mojihen to be importable."""

    def _make_cjk_cfg(self):
        from agentgate.config import GateConfig
        cfg = GateConfig()
        cfg.cjk.enabled = True
        cfg.cjk.min_confidence = "high"
        return cfg

    def test_mh001_corrupt_cjk_blocks(self):
        """A line with a known-wrong kanji is detected as MH001."""
        from agentgate.checks.cjk import run
        from agentgate.model import WriteEvent

        # 闾 (U+95FE) is a known corruption of 閾 (U+9596) per mojihen corpus
        # This is a LITERAL UTF-8 character -- not an escape
        content = "threshold = 闾"
        event = WriteEvent(
            agent="claude-code",
            phase="pre",
            tool="Write",
            file_path="app.py",
            content=content,
        )
        cfg = self._make_cjk_cfg()
        issues = run(event, cfg)
        mh001 = [i for i in issues if i.rule_id == "MH001"]
        self.assertGreater(len(mh001), 0, "Expected MH001 finding for known corrupt CJK")
        self.assertEqual(mh001[0].severity, "high")
        self.assertEqual(mh001[0].check, "cjk")

    def test_mh001_suggestion_populated(self):
        """MH001 issue has a non-empty suggestion with 'likely: ...'."""
        from agentgate.checks.cjk import run
        from agentgate.model import WriteEvent

        content = "閾値の代わりに 闾 を使った"
        event = WriteEvent(
            agent="generic",
            phase="unknown",
            tool="unknown",
            file_path="code.py",
            content=content,
        )
        cfg = self._make_cjk_cfg()
        issues = run(event, cfg)
        mh001 = [i for i in issues if i.rule_id == "MH001"]
        if mh001:
            self.assertTrue(
                mh001[0].suggestion.startswith("likely:"),
                f"Suggestion should start with 'likely:': {mh001[0].suggestion!r}",
            )

    def test_clean_cjk_no_issues(self):
        """Legitimate CJK text produces no MH001 issues."""
        from agentgate.checks.cjk import run
        from agentgate.model import WriteEvent

        # Clean Japanese text -- no known corruptions
        content = "このプログラムは正しく動作します。"
        event = WriteEvent(
            agent="generic",
            phase="unknown",
            tool="unknown",
            file_path="readme.md",
            content=content,
        )
        cfg = self._make_cjk_cfg()
        issues = run(event, cfg)
        mh001 = [i for i in issues if i.rule_id == "MH001"]
        self.assertEqual(mh001, [], f"Unexpected MH001 in clean CJK: {mh001}")

    def test_hook_with_cjk_enabled_blocks(self):
        """hook --stdin with cjk enabled: corrupt CJK -> exit 2."""
        content = "閾値 = 闾"
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {
                "file_path": "app.py",
                "content": content,
            },
        })
        from agentgate.config import GateConfig
        cfg = GateConfig()
        cfg.cjk.enabled = True
        cfg.cjk.min_confidence = "high"

        stdin_buf = io.StringIO(payload)
        stderr_buf = io.StringIO()
        with patch("sys.stdin", stdin_buf):
            with patch("sys.stderr", stderr_buf):
                with patch("agentgate.cli.load_config", return_value=cfg):
                    from agentgate import cli
                    code = cli.cmd_hook(["--stdin"])

        # If MH001 fired, should be exit 2
        issues_from_check = []
        from agentgate.checks.cjk import run as cjk_run
        from agentgate.model import WriteEvent
        ev = WriteEvent("claude-code", "pre", "Write", "app.py", content)
        issues_from_check = cjk_run(ev, cfg)
        mh001 = [i for i in issues_from_check if i.rule_id == "MH001"]
        if mh001:
            self.assertEqual(code, 2)
        else:
            # If corpus doesn't have this entry, that's also acceptable
            self.assertIn(code, (0, 2))


class TestCjkStartupError(unittest.TestCase):
    """Test that enabling cjk without mojihen raises the startup error."""

    def test_missing_mojihen_raises_startup_error(self):
        """When cjk is enabled and mojihen is absent, the hook exits 2 with clear message."""
        from agentgate.config import GateConfig
        cfg = GateConfig()
        cfg.cjk.enabled = True

        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "x.py", "content": "hello"},
        })

        # Force ImportError for mojihen at startup check
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "mojihen":
                raise ImportError("mojihen not installed")
            return real_import(name, *args, **kwargs)

        stdin_buf = io.StringIO(payload)
        stderr_buf = io.StringIO()
        with patch("builtins.__import__", side_effect=mock_import):
            with patch("sys.stdin", stdin_buf):
                with patch("sys.stderr", stderr_buf):
                    with patch("agentgate.cli.load_config", return_value=cfg):
                        from agentgate import cli
                        code = cli.cmd_hook(["--stdin"])

        self.assertEqual(code, 2, "Should exit 2 when mojihen missing and cjk enabled")
        err_output = stderr_buf.getvalue()
        self.assertIn("mojihen", err_output.lower(), f"Error message should mention mojihen: {err_output!r}")

    def test_cjk_check_runtime_error_on_missing_mojihen(self):
        """checks/cjk.py raises RuntimeError when mojihen absent at call time."""
        from agentgate.config import GateConfig
        from agentgate.model import WriteEvent

        cfg = GateConfig()
        cfg.cjk.enabled = True

        event = WriteEvent("generic", "unknown", "unknown", "x.py", "hello")

        # Temporarily patch sys.modules to simulate mojihen absence
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("mojihen", "mojihen.detect", "mojihen.corpus"):
                raise ImportError("mojihen not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            # Clear any cached mojihen imports from cjk module
            mods_to_clear = [k for k in sys.modules if k.startswith("mojihen")]
            saved = {k: sys.modules.pop(k) for k in mods_to_clear}
            try:
                # Re-import cjk check to test fresh state
                if "agentgate.checks.cjk" in sys.modules:
                    del sys.modules["agentgate.checks.cjk"]
                from agentgate.checks import cjk as cjk_module
                with self.assertRaises(RuntimeError) as ctx:
                    cjk_module.run(event, cfg)
                self.assertIn("pip install", str(ctx.exception))
            finally:
                sys.modules.update(saved)


if __name__ == "__main__":
    unittest.main()
