"""adapter.py -- Normalize stdin JSON hook payloads into WriteEvent.

Supports three payload shapes:
  1. Claude Code: {hook_event_name, tool_name, tool_input:{file_path, content|new_string}}
  2. Codex apply_patch: tool_input.command containing *** Begin Patch envelope
  3. Generic fallback: {file_path|path, content|text|new_string} at top level or tool_input

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
    # 1. Claude Code shape: has hook_event_name + tool_name
    # -----------------------------------------------------------------------
    hook_event_name = payload.get("hook_event_name")
    tool_name = payload.get("tool_name")

    if hook_event_name and tool_name:
        phase = _parse_phase(hook_event_name)
        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {}

        file_path = _extract_path(tool_input)
        content = _extract_content(tool_input)

        return WriteEvent(
            agent="claude-code",
            phase=phase,
            tool=str(tool_name),
            file_path=file_path,
            content=content,
        )

    # -----------------------------------------------------------------------
    # 2. Codex shape: tool_input.command containing apply_patch
    # -----------------------------------------------------------------------
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        command = tool_input.get("command")

        # command may be a string or a list (argv)
        if isinstance(command, list):
            command_str = " ".join(str(c) for c in command)
        elif isinstance(command, str):
            command_str = command
        else:
            command_str = ""

        if command_str and "*** Begin Patch" in command_str:
            file_path, added_text = parse_apply_patch(command_str)
            return WriteEvent(
                agent="codex",
                phase=_parse_phase(payload.get("hook_event_name")),
                tool="apply_patch",
                file_path=file_path or "<stdin>",
                content=added_text,
            )

        # tool_input present but not apply_patch -- try generic extraction from tool_input
        file_path = _extract_path(tool_input)
        content = _extract_content(tool_input)
        if content:
            return WriteEvent(
                agent="generic",
                phase=_parse_phase(payload.get("hook_event_name")),
                tool="unknown",
                file_path=file_path,
                content=content,
            )

    # -----------------------------------------------------------------------
    # 3. Generic / fallback: content at top level
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
