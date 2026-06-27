"""test_codex_hook.py -- End-to-end cmd_hook tests for Codex apply_patch payloads.

Tests verify:
- corrupt Codex PRE apply_patch -> exit 0 + stdout JSON deny (permissionDecision)
- clean Codex PRE apply_patch   -> exit 0 + stdout empty (no deny)
- corrupt Codex POST apply_patch -> exit 0 + stdout has NO permissionDecision (logging-only)
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from agentgate import cli


def _make_patch_envelope(filename: str, added_line: str) -> str:
    return (
        "*** Begin Patch\n"
        f"*** Add File: {filename}\n"
        f"+{added_line}\n"
        "*** End Patch"
    )


def _make_codex_payload(hook_event_name: str, patch_command: str) -> str:
    return json.dumps({
        "hook_event_name": hook_event_name,
        "tool_name": "apply_patch",
        "tool_input": {"command": patch_command},
    })


def _run_hook(stdin_content: str):
    """Run cmd_hook with captured stdin/stdout/stderr.

    Returns (exit_code, stdout_str).
    """
    fake_stdin = io.StringIO(stdin_content)
    fake_stdout = io.StringIO()
    fake_stderr = io.StringIO()
    with patch("sys.stdin", fake_stdin):
        with patch("sys.stdout", fake_stdout):
            with patch("sys.stderr", fake_stderr):
                exit_code = cli.cmd_hook(["--stdin"])
    return exit_code, fake_stdout.getvalue()


class TestCodexHookBlock(unittest.TestCase):
    """cmd_hook end-to-end for Codex apply_patch payloads."""

    def test_corrupt_codex_pre_returns_0_with_deny(self):
        """Corrupt Codex PRE apply_patch -> exit 0 and stdout contains JSON deny."""
        # AG-BIDI (high, always block) fires on a bidi char in added Python code.
        bidi_line = "x = " + chr(0x202E) + "dangerous"
        patch_cmd = _make_patch_envelope("app.py", bidi_line)
        payload = _make_codex_payload("PreToolUse", patch_cmd)

        exit_code, stdout = _run_hook(payload)

        self.assertEqual(exit_code, 0)
        self.assertIn('"permissionDecision": "deny"', stdout)
        self.assertIn('"hookEventName": "PreToolUse"', stdout)

    def test_clean_codex_pre_returns_0_no_deny(self):
        """Clean Codex PRE apply_patch -> exit 0 and stdout is empty (no deny)."""
        patch_cmd = _make_patch_envelope("app.py", "x = 1")
        payload = _make_codex_payload("PreToolUse", patch_cmd)

        exit_code, stdout = _run_hook(payload)

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.strip(), "")

    def test_corrupt_codex_post_returns_0_no_deny(self):
        """Corrupt Codex POST apply_patch -> exit 0, stdout has NO permissionDecision.

        PostToolUse cannot prevent the write; agentgate logs to stderr only.
        """
        bidi_line = chr(0x202E) + "override"
        patch_cmd = _make_patch_envelope("app.py", bidi_line)
        payload = _make_codex_payload("PostToolUse", patch_cmd)

        exit_code, stdout = _run_hook(payload)

        self.assertEqual(exit_code, 0)
        self.assertNotIn("permissionDecision", stdout)


if __name__ == "__main__":
    unittest.main()
