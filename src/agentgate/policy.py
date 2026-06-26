"""policy.py -- Severity-to-action mapping and suppression rules.

Policy:
  high   -> block (exit 2)
  medium -> warn  (exit 0, logged)
  low    -> ignore

Suppression:
  Only rule-specific directives: `agentgate: ignore[AG-INVIS]`
  NO bare `agentgate: ignore` (that would let models launder violations).
  AG-BIDI is never suppressible unless cfg.unicode.allow_bidi_suppression is True.
"""

from __future__ import annotations

import re
from typing import List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Issue
    from .config import GateConfig

# Pattern: agentgate: ignore[RULE1,RULE2] (with optional whitespace)
_SUPPRESS_RE = re.compile(r"agentgate:\s*ignore\[([^\]]+)\]")


def _parse_suppression(line_text: str) -> Optional[Set[str]]:
    """Return set of suppressed rule IDs found in this line, or None if none."""
    m = _SUPPRESS_RE.search(line_text)
    if not m:
        return None
    rules_str = m.group(1)
    rules = {r.strip() for r in rules_str.split(",") if r.strip()}
    return rules if rules else None


def _severity_to_action(severity: str, cfg: "GateConfig") -> str:
    """Map a severity string to an action string."""
    if severity == "high":
        return cfg.policy.high
    if severity == "medium":
        return cfg.policy.medium
    if severity == "low":
        return cfg.policy.low
    return "ignore"


def apply_suppression(
    issues: List["Issue"],
    content: str,
    cfg: "GateConfig",
) -> List["Issue"]:
    """Filter issues based on per-line suppression directives.

    Returns issues that survive suppression.
    """
    lines = content.splitlines()
    # Build line->suppressed_rules map
    suppression_map: dict = {}
    for i, line in enumerate(lines, start=1):
        rules = _parse_suppression(line)
        if rules is not None:
            suppression_map[i] = rules

    surviving: List["Issue"] = []
    for issue in issues:
        suppressed_rules = suppression_map.get(issue.line)
        if suppressed_rules is not None and issue.rule_id in suppressed_rules:
            # AG-BIDI is only suppressible if explicitly allowed
            if issue.rule_id == "AG-BIDI" and not cfg.unicode.allow_bidi_suppression:
                surviving.append(issue)  # cannot suppress AG-BIDI
            else:
                continue  # suppressed
        else:
            surviving.append(issue)

    return surviving


def decide_block(issues: List["Issue"], cfg: "GateConfig") -> bool:
    """Return True if any issue maps to 'block' action."""
    for issue in issues:
        action = _severity_to_action(issue.severity, cfg)
        if action == "block":
            return True
    return False


def filter_actionable(issues: List["Issue"], cfg: "GateConfig") -> List["Issue"]:
    """Return only issues that are not 'ignore'."""
    return [
        issue for issue in issues
        if _severity_to_action(issue.severity, cfg) != "ignore"
    ]
