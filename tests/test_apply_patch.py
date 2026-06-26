"""test_apply_patch.py -- Tests for apply_patch.py envelope parser."""

from __future__ import annotations

import sys
import unittest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from agentgate.apply_patch import parse_apply_patch


class TestParseApplyPatch(unittest.TestCase):

    def test_add_file(self):
        patch = (
            "*** Begin Patch\n"
            "*** Add File: src/new.py\n"
            "+line one\n"
            "+line two\n"
            "*** End Patch"
        )
        path, content = parse_apply_patch(patch)
        self.assertEqual(path, "src/new.py")
        self.assertEqual(content, "line one\nline two")

    def test_update_file(self):
        patch = (
            "*** Begin Patch\n"
            "*** Update File: existing.py\n"
            " context line\n"
            "+added line\n"
            "-removed line\n"
            "*** End Patch"
        )
        path, content = parse_apply_patch(patch)
        self.assertEqual(path, "existing.py")
        self.assertEqual(content, "added line")
        self.assertNotIn("context", content)
        self.assertNotIn("removed", content)

    def test_delete_file(self):
        patch = (
            "*** Begin Patch\n"
            "*** Delete File: old.py\n"
            "*** End Patch"
        )
        path, content = parse_apply_patch(patch)
        self.assertEqual(path, "old.py")
        self.assertEqual(content, "")

    def test_multi_hunk_takes_first_path(self):
        patch = (
            "*** Begin Patch\n"
            "*** Add File: first.py\n"
            "+first line\n"
            "*** Update File: second.py\n"
            "+second line\n"
            "*** End Patch"
        )
        path, content = parse_apply_patch(patch)
        self.assertEqual(path, "first.py")
        # All added lines from all files
        self.assertIn("first line", content)
        self.assertIn("second line", content)

    def test_excludes_plus_plus_plus_header(self):
        patch = (
            "*** Begin Patch\n"
            "*** Add File: f.py\n"
            "+++ b/f.py\n"
            "+real added line\n"
            "*** End Patch"
        )
        path, content = parse_apply_patch(patch)
        self.assertNotIn("+++", content)
        self.assertIn("real added line", content)

    def test_no_begin_marker(self):
        path, content = parse_apply_patch("just some text")
        self.assertEqual(path, "")
        self.assertEqual(content, "")

    def test_empty_string(self):
        path, content = parse_apply_patch("")
        self.assertEqual(path, "")
        self.assertEqual(content, "")

    def test_non_string_input(self):
        path, content = parse_apply_patch(None)  # type: ignore
        self.assertEqual(path, "")
        self.assertEqual(content, "")

    def test_missing_end_marker(self):
        # Unterminated envelope -- should still extract what it can
        patch = (
            "*** Begin Patch\n"
            "*** Add File: x.py\n"
            "+line\n"
        )
        path, content = parse_apply_patch(patch)
        self.assertEqual(path, "x.py")
        self.assertIn("line", content)

    def test_path_with_spaces(self):
        patch = (
            "*** Begin Patch\n"
            "*** Add File: path/with spaces/file.py\n"
            "+x = 1\n"
            "*** End Patch"
        )
        path, content = parse_apply_patch(patch)
        self.assertEqual(path, "path/with spaces/file.py")

    def test_context_lines_not_included(self):
        patch = (
            "*** Begin Patch\n"
            "*** Update File: foo.py\n"
            " this is context\n"
            "+this is added\n"
            "*** End Patch"
        )
        _, content = parse_apply_patch(patch)
        self.assertNotIn("this is context", content)
        self.assertIn("this is added", content)


if __name__ == "__main__":
    unittest.main()
