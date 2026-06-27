"""adapter.py -- Normalize stdin JSON hook payloads into WriteEvent.

Supports four payload shapes (checked in this order):
  1. apply_patch (Codex): tool_name=="apply_patch" OR tool_input.command contains
     *** Begin Patch envelope.  Checked FIRST so the real Codex payload
     (hook_event_name + tool_name="apply_patch" + tool_input.command) is not
     misrouted to the Claude Code branch which cannot extract content from {command}.
  2. Claude Code: {hook_event_name, tool_name, tool_input:{file_path, content|new_string}}
  3. Generic with tool_input: tool_input present, content extractable.
  4. Generic fallback: {file_path|path, content|text|new_string} at top level.

Never raises on bad input -- tolerant extraction throughout.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .apply_patch import parse_apply_patch
from .model import WriteEvent


def _extract_content(obj: Dict[str, Any]) -> str:
    """Extract content text from a tool_input-like dict."""
    return (
        obj.get("content")
        or obj.get("new_string")
        or obj.get("text")
        or ""
    )


def _extract_path(obj: Dict[str, Any]) -> str:
    """Extract file path from a tool_input-like dict."""
    return (
        obj.get("file_path")
        or obj.get("path")
        or "<stdin>"
    )


def _parse_phase(hook_event_name: Optional[str]) -> str:
    if not hook_event_name:
        return "unknown"
    hen = hook_event_name.lower()
    if "pre" in hen:
        return "pre"
    if "post" in hen:
        return "post"
    return "unknown"


def from_stdin_json(raw: str) -> WriteEvent:
    """Parse a raw stdin string into a WriteEvent.

    Returns a WriteEvent with empty content when nothing can be extracted.
    Caller should check event.content and exit 0 when empty (nothing to gate).
    """
    if not raw or not raw.strip():
        return WriteEvent(agent="generic", phase="unknown", tool="unknown",
                          file_path="<stdin>", content="")

    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return WriteEvent(agent="generic", phase="unknown", tool="unknown",
                          file_path="<stdin>", content="")

    if not isinstance(payload, dict):
        return WriteEvent(agent="generic", phase="unknown", tool="unknown",
                          file_path="<stdin>", content="")

    # -----------------------------------------------------------------------
    # Pre-extract fields used by multiple branches below
    # -----------------------------------------------------------------------
    hook_event_name = payload.get("hook_event_name")
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    ti: Dict[str, Any] = tool_input if isinstance(tool_input, dict) else {}

    # Build command_str from ti.command (str or argv list)
    _cmd = ti.get("command")
    if isinstance(_cmd, list):
        command_str = " ".join(str(c) for c in _cmd)
    elif isinstance(_cmd, str):
        command_str = _cmd
    else:
        command_str = ""

    # -----------------------------------------------------------------------
    # 1. apply_patch branch (checked FIRST to prevent misroute via Branch 2)
    #    Fires when tool_name is "apply_patch" OR the command contains the
    #    apply_patch envelope -- covers the real Codex payload shape which
    #    carries BOTH hook_event_name AND tool_name="apply_patch".
    # -----------------------------------------------------------------------
    if tool_name == "apply_patch" or "*** Begin Patch" in command_str:
        phase = _parse_phase(hook_event_name)
        if "*** Begin Patch" in command_str:
            file_path, added_text = parse_apply_patch(command_str)
            return WriteEvent(
                agent="codex",
                phase=phase,
                tool="apply_patch",
                file_path=file_path or "<stdin>",
                content=added_text,
            )
        # tool_name says apply_patch but no parsable envelope -- fail-open
        return WriteEvent(
            agent="codex",
            phase=phase,
            tool="apply_patch",
            file_path="<stdin>",
            content="",
        )

    # -----------------------------------------------------------------------
    # 2. Claude Code shape: has hook_event_name + tool_name
    #    (apply_patch already handled above, so this is Write/Edit/etc.)
    # -----------------------------------------------------------------------
    if hook_event_name and tool_name:
        phase = _parse_phase(hook_event_name)
        file_path = _extract_path(ti)
        content = _extract_content(ti)
        return WriteEvent(
            agent="claude-code",
            phase=phase,
            tool=str(tool_name),
            file_path=file_path,
            content=content,
        )

    # -----------------------------------------------------------------------
    # 3. tool_input present but not apply_patch -- try generic extraction
    # -----------------------------------------------------------------------
    if ti:
        file_path = _extract_path(ti)
        content = _extract_content(ti)
        if content:
            return WriteEvent(
                agent="generic",
                phase=_parse_phase(hook_event_name),
                tool="unknown",
                file_path=file_path,
                content=content,
            )

    # -----------------------------------------------------------------------
    # 4. Generic / fallback: content at top level
    # -----------------------------------------------------------------------
    file_path = _extract_path(payload)
    content = _extract_content(payload)

    return WriteEvent(
        agent="generic",
        phase="unknown",
        tool="unknown",
        file_path=file_path,
        content=content,
    )
