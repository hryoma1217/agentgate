"""test_adapter.py -- Tests for adapter.py payload normalization."""

from __future__ import annotations

import json
import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from agentgate.adapter import from_stdin_json
from agentgate.model import WriteEvent


class TestClaudeCodeAdapter(unittest.TestCase):
    """Claude Code hook payloads."""

    def _make_payload(self, hook_event_name, tool_name, tool_input):
        return json.dumps({
            "hook_event_name": hook_event_name,
            "tool_name": tool_name,
            "tool_input": tool_input,
        })

    def test_pre_write(self):
        raw = self._make_payload("PreToolUse", "Write", {
            "file_path": "app.py",
            "content": "print('hello')",
        })
        event = from_stdin_json(raw)
        self.assertEqual(event.agent, "claude-code")
        self.assertEqual(event.phase, "pre")
        self.assertEqual(event.tool, "Write")
        self.assertEqual(event.file_path, "app.py")
        self.assertEqual(event.content, "print('hello')")

    def test_post_edit(self):
        raw = self._make_payload("PostToolUse", "Edit", {
            "file_path": "main.go",
            "new_string": "func main() {}",
        })
        event = from_stdin_json(raw)
        self.assertEqual(event.agent, "claude-code")
        self.assertEqual(event.phase, "post")
        self.assertEqual(event.tool, "Edit")
        self.assertEqual(event.file_path, "main.go")
        self.assertEqual(event.content, "func main() {}")

    def test_missing_tool_input(self):
        raw = json.dumps({
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
        })
        event = from_stdin_json(raw)
        self.assertEqual(event.agent, "claude-code")
        self.assertEqual(event.content, "")

    def test_case_insensitive_phase(self):
        raw = self._make_payload("PRETOOLUSE", "Write", {"content": "x"})
        event = from_stdin_json(raw)
        self.assertEqual(event.phase, "pre")


class TestCodexAdapter(unittest.TestCase):
    """Codex apply_patch payloads."""

    def _codex_payload(self, command, hook_event_name="PreToolUse"):
        return json.dumps({
            "hook_event_name": hook_event_name,
            "tool_input": {"command": command},
        })

    def test_add_file(self):
        patch = (
            "*** Begin Patch\n"
            "*** Add File: src/foo.py\n"
            "+def hello():\n"
            "+    return 42\n"
            "*** End Patch"
        )
        event = from_stdin_json(self._codex_payload(patch))
        self.assertEqual(event.agent, "codex")
        self.assertEqual(event.tool, "apply_patch")
        self.assertEqual(event.file_path, "src/foo.py")
        self.assertIn("def hello():", event.content)
        self.assertIn("return 42", event.content)

    def test_update_file(self):
        patch = (
            "*** Begin Patch\n"
            "*** Update File: README.md\n"
            " existing line\n"
            "+new line added\n"
            "*** End Patch"
        )
        event = from_stdin_json(self._codex_payload(patch))
        self.assertEqual(event.tool, "apply_patch")
        self.assertIn("new line added", event.content)
        self.assertNotIn("existing line", event.content)

    def test_unparsable_patch_fail_open(self):
        # No Begin Patch marker -> fail open with empty content
        event = from_stdin_json(self._codex_payload("some random command"))
        self.assertEqual(event.content, "")

    def test_argv_command(self):
        patch = (
            "*** Begin Patch\n"
            "*** Add File: x.py\n"
            "+x = 1\n"
            "*** End Patch"
        )
        payload = json.dumps({
            "tool_input": {"command": ["apply_patch", patch]},
        })
        event = from_stdin_json(payload)
        self.assertEqual(event.tool, "apply_patch")
        self.assertIn("x = 1", event.content)


class TestCodexRealShape(unittest.TestCase):
    """Regression tests for the REAL Codex payload shape.

    The real Codex apply_patch hook carries BOTH hook_event_name AND tool_name
    (like Claude Code), but tool_input holds only {command}.  Previously this
    was misrouted to the Claude Code branch which found no content/new_string
    -> returned empty content -> gate exited 0 (fail-open MISS).
    """

    def _real_codex_payload(self, hook_event_name, patch_command, extra=None):
        d = {
            "hook_event_name": hook_event_name,
            "tool_name": "apply_patch",
            "tool_input": {"command": patch_command},
        }
        if extra:
            d.update(extra)
        return json.dumps(d)

    def test_real_codex_pre_routes_to_codex(self):
        """Real Codex PreToolUse payload must route to agent='codex', NOT 'claude-code'."""
        patch = (
            "*** Begin Patch\n"
            "*** Add File: app.py\n"
            "+x = 1\n"
            "*** End Patch"
        )
        raw = self._real_codex_payload("PreToolUse", patch)
        event = from_stdin_json(raw)
        self.assertEqual(event.agent, "codex")
        self.assertNotEqual(event.agent, "claude-code")
        self.assertEqual(event.tool, "apply_patch")
        self.assertEqual(event.phase, "pre")
        self.assertIn("x = 1", event.content)
        self.assertEqual(event.file_path, "app.py")

    def test_real_codex_post_has_tool_response(self):
        """Real Codex PostToolUse payload (with tool_response) -> agent='codex', phase='post'."""
        patch = (
            "*** Begin Patch\n"
            "*** Add File: app.py\n"
            "+x = 1\n"
            "*** End Patch"
        )
        raw = self._real_codex_payload("PostToolUse", patch, extra={"tool_response": {}})
        event = from_stdin_json(raw)
        self.assertEqual(event.agent, "codex")
        self.assertEqual(event.phase, "post")

    def test_tool_name_apply_patch_unparsable(self):
        """tool_name=apply_patch but no patch envelope -> agent='codex', content='' (fail-open)."""
        raw = self._real_codex_payload("PreToolUse", "garbage")
        event = from_stdin_json(raw)
        self.assertEqual(event.agent, "codex")
        self.assertEqual(event.content, "")


class TestGenericAdapter(unittest.TestCase):
    """Generic fallback payloads."""

    def test_top_level_content(self):
        raw = json.dumps({"file_path": "a.txt", "content": "hello"})
        event = from_stdin_json(raw)
        self.assertEqual(event.agent, "generic")
        self.assertEqual(event.content, "hello")
        self.assertEqual(event.file_path, "a.txt")

    def test_top_level_text(self):
        raw = json.dumps({"path": "b.txt", "text": "world"})
        event = from_stdin_json(raw)
        self.assertEqual(event.content, "world")

    def test_empty_json(self):
        event = from_stdin_json(json.dumps({}))
        self.assertEqual(event.content, "")

    def test_non_json(self):
        event = from_stdin_json("not json at all")
        self.assertEqual(event.content, "")
        self.assertEqual(event.agent, "generic")

    def test_empty_string(self):
        event = from_stdin_json("")
        self.assertEqual(event.content, "")

    def test_whitespace_only(self):
        event = from_stdin_json("   \n  ")
        self.assertEqual(event.content, "")


if __name__ == "__main__":
    unittest.main()
