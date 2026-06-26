"""test_hook_exit.py -- Tests for hook subcommand exit codes.

pre-block=2, post-block=2, allow=0, non-JSON=0, empty=0.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from agentgate import cli


def _run_hook(stdin_content: str, config_override=None) -> int:
    """Run the hook subcommand with given stdin content.  Returns exit code."""
    with patch("sys.stdin", io.StringIO(stdin_content)):
        with patch("sys.stderr", io.StringIO()):
            if config_override is not None:
                with patch("agentgate.cli.load_config", return_value=config_override):
                    return cli.cmd_hook(["--stdin"])
            return cli.cmd_hook(["--stdin"])


def _make_claude_payload(
    hook_event: str, content: str, file_path: str = "app.py"
) -> str:
    return json.dumps({
        "hook_event_name": hook_event,
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": content,
        },
    })


class TestHookExitCodes(unittest.TestCase):

    def test_allow_clean_content(self):
        """Clean content -> exit 0."""
        payload = _make_claude_payload("PreToolUse", "def hello():\n    return 42\n")
        result = _run_hook(payload)
        self.assertEqual(result, 0)

    def test_pre_bidi_blocks(self):
        """Bidi control in PreToolUse -> exit 2."""
        content = "x = " + chr(0x202E) + "dangerous"
        payload = _make_claude_payload("PreToolUse", content, "app.py")
        result = _run_hook(payload)
        self.assertEqual(result, 2)

    def test_post_bidi_blocks(self):
        """Bidi control in PostToolUse -> exit 2 (feedback mode)."""
        content = chr(0x202E) + "override"
        payload = _make_claude_payload("PostToolUse", content, "app.py")
        result = _run_hook(payload)
        self.assertEqual(result, 2)

    def test_non_json_stdin(self):
        """Non-JSON stdin -> fail open, exit 0."""
        result = _run_hook("this is not json at all")
        self.assertEqual(result, 0)

    def test_empty_stdin(self):
        """Empty stdin -> exit 0."""
        result = _run_hook("")
        self.assertEqual(result, 0)

    def test_whitespace_only_stdin(self):
        """Whitespace-only stdin -> exit 0."""
        result = _run_hook("   \n\t  ")
        self.assertEqual(result, 0)

    def test_empty_content_in_payload(self):
        """Valid JSON but empty content -> exit 0."""
        payload = json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "x.py", "content": ""},
        })
        result = _run_hook(payload)
        self.assertEqual(result, 0)

    def test_invis_char_in_code_blocks(self):
        """Invisible char inside identifier in code file -> exit 2."""
        content = "foo" + chr(0x200B) + "bar = 1"
        payload = _make_claude_payload("PreToolUse", content, "main.py")
        result = _run_hook(payload)
        self.assertEqual(result, 2)

    def test_missing_stdin_flag(self):
        """Missing --stdin flag -> exit 2."""
        with patch("sys.stdin", io.StringIO("")):
            with patch("sys.stderr", io.StringIO()):
                result = cli.cmd_hook([])
        self.assertEqual(result, 2)

    def test_doc_file_invis_not_blocked(self):
        """Invisible char in markdown file -> not blocked (doc profile)."""
        content = "Hello " + chr(0x200B) + " world"
        payload = _make_claude_payload("PreToolUse", content, "README.md")
        result = _run_hook(payload)
        self.assertEqual(result, 0)

    def test_clean_markdown_exit_0(self):
        """Clean markdown content -> exit 0."""
        content = "# Title\n\nThis is **bold** text.\n"
        payload = _make_claude_payload("PreToolUse", content, "README.md")
        result = _run_hook(payload)
        self.assertEqual(result, 0)

    def test_json_object_not_hook_payload(self):
        """Arbitrary JSON dict with no content -> exit 0."""
        result = _run_hook(json.dumps({"foo": "bar", "baz": 42}))
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
