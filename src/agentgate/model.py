"""model.py -- Core dataclasses for agentgate.

WriteEvent: normalized representation of an agent write action.
Issue: a single finding from a check.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WriteEvent:
    """Normalized agent write event extracted from a hook payload."""

    agent: str    # "claude-code" | "codex" | "generic"
    phase: str    # "pre" | "post" | "unknown"
    tool: str     # "Write" | "Edit" | "apply_patch" | "unknown"
    file_path: str  # best-effort; "<stdin>" if absent
    content: str  # the added/written text to inspect


@dataclass
class Issue:
    """A single finding from a check run."""

    check: str      # "cjk" | "unicode"
    rule_id: str    # "MH001" | "AG-BIDI" | "AG-INVIS" | "AG-HOMO"
    severity: str   # "high" | "medium" | "low"
    line: int
    col: int
    message: str
    excerpt: str
    suggestion: str = field(default="")
