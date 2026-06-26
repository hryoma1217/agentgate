"""report.py -- Output formatters for agentgate.

block_report(issues) -> str  -- model-readable block message for stderr
format_tty / format_json / format_sarif -- scan output formatters
"""

from __future__ import annotations

import json
import os
import sys
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from .model import Issue

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_DIM = "\033[2m"


def _color_enabled() -> bool:
    return (
        hasattr(sys.stdout, "isatty")
        and sys.stdout.isatty()
        and os.environ.get("NO_COLOR", "") == ""
        and os.environ.get("TERM", "") != "dumb"
    )


def _c(code: str, text: str) -> str:
    if _color_enabled():
        return f"{code}{text}{_RESET}"
    return text


# ---------------------------------------------------------------------------
# Block report (model-readable, written to stderr)
# ---------------------------------------------------------------------------

def block_report(issues: List["Issue"], file_path: str = "<stdin>") -> str:
    """Build the model-readable block report string.

    Format mirrors design section 3.5:
      agentgate: BLOCKED -- N issue(s) to fix before this write

        file:line:col  check/rule_id SEVERITY  'excerpt'  -> suggestion
            message text

      Fix these and re-emit.
    """
    n = len(issues)
    lines = [
        f"agentgate: BLOCKED -- {n} issue(s) to fix before this write",
        "",
    ]

    for issue in issues:
        fp = issue_file_path(issue, file_path)
        sev = issue.severity.upper()
        suggestion_str = f"  -> {issue.suggestion}" if issue.suggestion else ""
        lines.append(
            f"  {fp}:{issue.line}:{issue.col}  "
            f"{issue.check}/{issue.rule_id} {sev}  "
            f"'{issue.excerpt}'{suggestion_str}"
        )
        lines.append(f"      {issue.message}")

    lines.append("")
    lines.append("  Fix these and re-emit.")
    return "\n".join(lines)


def warn_report(issues: List["Issue"], file_path: str = "<stdin>") -> str:
    """Build a non-blocking warning report (same layout as block_report).

    Used in hook mode for warn-level issues: surfaced to stderr, exit 0.
    """
    n = len(issues)
    lines = [
        f"agentgate: WARNING -- {n} non-blocking issue(s)",
        "",
    ]
    for issue in issues:
        fp = issue_file_path(issue, file_path)
        sev = issue.severity.upper()
        suggestion_str = f"  -> {issue.suggestion}" if issue.suggestion else ""
        lines.append(
            f"  {fp}:{issue.line}:{issue.col}  "
            f"{issue.check}/{issue.rule_id} {sev}  "
            f"'{issue.excerpt}'{suggestion_str}"
        )
        lines.append(f"      {issue.message}")
    return "\n".join(lines)


def issue_file_path(issue: "Issue", default: str) -> str:
    """Return the file path for an issue (uses default if not set on issue)."""
    return default


# ---------------------------------------------------------------------------
# TTY scan format
# ---------------------------------------------------------------------------

_SEV_COLOR = {
    "high": _RED,
    "medium": _YELLOW,
    "low": _CYAN,
}


def format_tty(issues: List["Issue"], file_path: str = "") -> str:
    lines: List[str] = []
    for issue in issues:
        fp = file_path or "<stdin>"
        sev_label = _c(_SEV_COLOR.get(issue.severity, ""), issue.severity.upper())
        rule_label = _c(_CYAN, f"{issue.check}/{issue.rule_id}")
        suggestion_str = f"  {_c(_GREEN, '-> ' + issue.suggestion)}" if issue.suggestion else ""
        lines.append(
            f"{_c(_BOLD, fp)}:{issue.line}:{issue.col}  "
            f"{rule_label} {sev_label}  "
            f"{_c(_BOLD, repr(issue.excerpt))}{suggestion_str}"
        )
        lines.append(f"  {_c(_DIM, issue.message)}")

    n = len(issues)
    if n == 0:
        lines.append(_c(_GREEN, "agentgate: no issues"))
    else:
        plural = "issue" if n == 1 else "issues"
        lines.append(_c(_BOLD, f"\nagentgate: {n} {plural}"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON scan format
# ---------------------------------------------------------------------------

def _issue_to_dict(issue: "Issue", file_path: str = "") -> dict:
    return {
        "check": issue.check,
        "rule_id": issue.rule_id,
        "severity": issue.severity,
        "file": file_path or "",
        "line": issue.line,
        "col": issue.col,
        "message": issue.message,
        "excerpt": issue.excerpt,
        "suggestion": issue.suggestion,
    }


def format_json(issues: List["Issue"], file_path: str = "") -> str:
    payload = {
        "version": "1",
        "tool": "agentgate",
        "issues": [_issue_to_dict(i, file_path) for i in issues],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# SARIF 2.1.0 format
# ---------------------------------------------------------------------------

_SARIF_LEVEL = {
    "high": "error",
    "medium": "warning",
    "low": "note",
}

_RULE_DESCRIPTIONS = {
    "AG-BIDI": "Bidi control character that can visually reorder source code (Trojan-Source).",
    "AG-INVIS": "Invisible character (zero-width space, soft hyphen, etc.) inside identifier or string.",
    "AG-HOMO": "Homoglyph: Cyrillic or Greek character that looks like ASCII inside an identifier.",
    "MH001": "Known LLM CJK corruption: a character in the mojihen corpus of confirmed near-miss substitutions.",
    "MH002": "Mixed-script token: Han characters mixed with Latin or Cyrillic.",
    "MH003": "Isolated CJK in ASCII context: CJK appearing inside an otherwise-ASCII identifier.",
}

_RULE_NAMES = {
    "AG-BIDI": "bidi-control",
    "AG-INVIS": "invisible-char",
    "AG-HOMO": "homoglyph",
    "MH001": "known-cjk-corruption",
    "MH002": "mixed-script-token",
    "MH003": "isolated-cjk",
}


def format_sarif(issues: List["Issue"], file_path: str = "") -> str:
    rule_ids_seen = sorted({i.rule_id for i in issues})
    rules = []
    for rid in rule_ids_seen:
        rules.append({
            "id": rid,
            "name": _RULE_NAMES.get(rid, rid),
            "shortDescription": {"text": _RULE_DESCRIPTIONS.get(rid, rid)},
            "defaultConfiguration": {"level": "error"},
        })

    results = []
    for issue in issues:
        results.append({
            "ruleId": issue.rule_id,
            "level": _SARIF_LEVEL.get(issue.severity, "warning"),
            "message": {"text": issue.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": file_path or ""},
                        "region": {
                            "startLine": issue.line,
                            "startColumn": issue.col,
                        },
                    }
                }
            ],
        })

    sarif = {
        "$schema": "https://schemastore.azurewebsites.net/schemas/json/sarif-2.1.0-rtm.5.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "agentgate",
                        "version": "0.1.0",
                        "informationUri": "https://github.com/hryoma1217/agentgate",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, ensure_ascii=False, indent=2)
