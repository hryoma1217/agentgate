"""test_scan.py -- Tests for scan subcommand: fixtures, JSON/SARIF validity."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))

from agentgate import cli


def _run_scan(args, extra_stdin="") -> tuple:
    """Run scan subcommand, return (exit_code, stdout, stderr)."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with patch("sys.stdout", stdout_buf):
        with patch("sys.stderr", stderr_buf):
            code = cli.cmd_scan(args)
    return code, stdout_buf.getvalue(), stderr_buf.getvalue()


class TestScanFixtures(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name: str, content: str) -> str:
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_clean_file_exit_0(self):
        path = self._write("clean.py", "def hello():\n    return 42\n")
        code, out, err = _run_scan([path])
        self.assertEqual(code, 0)

    def test_bidi_file_exit_1(self):
        content = "x = " + chr(0x202E) + "dangerous\n"
        path = self._write("bad.py", content)
        code, out, err = _run_scan([path])
        self.assertEqual(code, 1)

    def test_json_format_valid(self):
        content = "y = " + chr(0x202E) + "x\n"
        path = self._write("bidi.py", content)
        code, out, err = _run_scan([path, "--format", "json"])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(data["version"], "1")
        self.assertEqual(data["tool"], "agentgate")
        self.assertIn("issues", data)
        self.assertGreater(len(data["issues"]), 0)
        issue = data["issues"][0]
        self.assertIn("rule_id", issue)
        self.assertIn("severity", issue)
        self.assertIn("line", issue)
        self.assertIn("col", issue)

    def test_sarif_format_valid(self):
        content = chr(0x202A) + "text\n"
        path = self._write("bidi2.py", content)
        code, out, err = _run_scan([path, "--format", "sarif"])
        self.assertEqual(code, 1)
        sarif = json.loads(out)
        self.assertIn("$schema", sarif)
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertIn("runs", sarif)
        run = sarif["runs"][0]
        self.assertIn("tool", run)
        self.assertIn("results", run)
        self.assertGreater(len(run["results"]), 0)

    def test_no_paths_error(self):
        code, out, err = _run_scan([])
        self.assertEqual(code, 2)

    def test_invalid_format_error(self):
        path = self._write("x.py", "x = 1\n")
        code, out, err = _run_scan([path, "--format", "xml"])
        self.assertEqual(code, 2)

    def test_multiple_files(self):
        path1 = self._write("a.py", "clean code\n")
        path2 = self._write("b.py", "x = " + chr(0x202E) + "y\n")
        code, out, err = _run_scan([path1, path2])
        self.assertEqual(code, 1)

    def test_markdown_clean(self):
        content = "# Title\n\nThis is clean markdown.\n"
        path = self._write("README.md", content)
        code, out, err = _run_scan([path])
        self.assertEqual(code, 0)

    def test_directory_scan(self):
        subdir = os.path.join(self.tmpdir, "subdir")
        os.makedirs(subdir)
        self._write("clean.py", "x = 1\n")
        bad_path = os.path.join(subdir, "bad.py")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write(chr(0x202E) + "code\n")
        code, out, err = _run_scan([self.tmpdir])
        self.assertEqual(code, 1)

    def test_json_empty_results(self):
        path = self._write("clean.py", "x = 1\n")
        code, out, err = _run_scan([path, "--format", "json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["issues"], [])


if __name__ == "__main__":
    unittest.main()
