#!/usr/bin/env python3
"""real_gate.py -- invoke the actual agentgate CLI as a Codex hook.

Adds ../src to sys.path and runs agentgate.cli.cmd_hook(["--stdin"]) so a real
`codex exec` PreToolUse hook exercises the shipped gate (not a stand-in).
"""
import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, os.path.abspath(_SRC))

from agentgate import cli  # noqa: E402

if __name__ == "__main__":
    # Invoke the real shipped entrypoint (main -> _enable_utf8_io -> cmd_hook).
    # Calling cmd_hook directly would bypass the Windows UTF-8 stdin fix and
    # mis-decode the payload's bidi bytes under cp932 (fail-open).
    sys.exit(cli.main(["hook", "--stdin"]))
