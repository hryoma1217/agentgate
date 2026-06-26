"""apply_patch.py -- Parse a Codex apply_patch envelope.

Handles the envelope format:
  *** Begin Patch
  *** Add File: path/to/file
  +added line
  +another added line
  *** Update File: path/to/other
  context line
  +added line
   more context
  *** End Patch

Returns (path, added_text) where:
  - path is the first Add File or Update File path found
  - added_text is the joined added lines ('+'-prefixed, excluding '+++' diff headers)

Returns ("", "") if the envelope is missing or cannot be parsed.
"""

from __future__ import annotations

from typing import Tuple


def parse_apply_patch(command: str) -> Tuple[str, str]:
    """Parse a Codex apply_patch command string.

    Returns (file_path, added_text).  On any parse failure returns ("", "").
    """
    if not isinstance(command, str):
        return ("", "")

    # Locate envelope boundaries
    begin_marker = "*** Begin Patch"
    end_marker = "*** End Patch"

    begin_idx = command.find(begin_marker)
    if begin_idx == -1:
        return ("", "")

    end_idx = command.find(end_marker, begin_idx)
    if end_idx == -1:
        # Accept unterminated envelope -- take everything after begin
        envelope = command[begin_idx + len(begin_marker):]
    else:
        envelope = command[begin_idx + len(begin_marker):end_idx]

    lines = envelope.splitlines()

    file_path = ""
    added_lines = []

    for line in lines:
        if line.startswith("*** Add File:"):
            candidate = line[len("*** Add File:"):].strip()
            if candidate and not file_path:
                file_path = candidate
        elif line.startswith("*** Update File:"):
            candidate = line[len("*** Update File:"):].strip()
            if candidate and not file_path:
                file_path = candidate
        elif line.startswith("*** Delete File:"):
            # Deletions have no added content; note path but no lines
            candidate = line[len("*** Delete File:"):].strip()
            if candidate and not file_path:
                file_path = candidate
        elif line.startswith("+") and not line.startswith("+++"):
            # Added line: strip the leading '+'
            added_lines.append(line[1:])
        # Context lines (no prefix or space prefix) and removed lines ('-') are ignored

    added_text = "\n".join(added_lines)
    return (file_path, added_text)
