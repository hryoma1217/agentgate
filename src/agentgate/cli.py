"""cli.py -- agentgate command-line interface.

Subcommands:
  agentgate hook --stdin        Primary: agent hook entrypoint (Pre/PostToolUse)
  agentgate scan PATH...        Same checks over files (CI / manual); tty|json|sarif
  agentgate checks              List checks + enabled state + missing deps
  agentgate --version

Exit codes:
  hook:  0 = allow; 2 = block (deny in Pre / feedback in Post) or error
  scan:  0 = no blocking findings; 1 = blocking findings; 2 = error
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from .config import load_config

# ---------------------------------------------------------------------------
# UTF-8 stdio fix (Windows cp932)
# ---------------------------------------------------------------------------

def _enable_utf8_io() -> None:
    """Force UTF-8 on stdio so Unicode output is not mangled on Windows."""
    out = getattr(sys.stdout, "reconfigure", None)
    if out is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    err = getattr(sys.stderr, "reconfigure", None)
    if err is not None:
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    inp = getattr(sys.stdin, "reconfigure", None)
    if inp is not None:
        try:
            sys.stdin.reconfigure(encoding="utf-8")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Skip dirs / binary detection (mirrors mojihen)
# ---------------------------------------------------------------------------

_SKIP_DIRS = {
    ".git", "node_modules", ".venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".tox",
}


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(8192)
        return b"\x00" in chunk
    except OSError:
        return True


def _read_source(path: Path) -> Optional[str]:
    if _is_binary(path):
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def collect_files(paths: List[Path]) -> List[Path]:
    result: List[Path] = []
    for p in paths:
        if p.is_file():
            result.append(p)
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                dirs[:] = [
                    d for d in dirs
                    if d not in _SKIP_DIRS and not d.startswith(".")
                ]
                for fname in files:
                    result.append(Path(root) / fname)
    return result


# ---------------------------------------------------------------------------
# hook subcommand
# ---------------------------------------------------------------------------

def cmd_hook(args: List[str]) -> int:
    """agentgate hook --stdin

    Reads a JSON hook payload from stdin, runs enabled checks, applies policy.

    Exit codes:
      0 = allow
      2 = block (deny in PreToolUse; feedback in PostToolUse)
    """
    if "--stdin" not in args:
        print("agentgate hook: expected --stdin flag", file=sys.stderr)
        return 2

    # Parse optional --config
    config_path: Optional[Path] = None
    for i, arg in enumerate(args):
        if arg in ("--config", "-c") and i + 1 < len(args):
            config_path = Path(args[i + 1])
        elif arg.startswith("--config="):
            config_path = Path(arg.split("=", 1)[1])

    # Load config (with startup dep check)
    cfg = load_config(explicit_path=config_path)

    # Startup check: if cjk is enabled, ensure mojihen is importable
    if cfg.cjk.enabled:
        try:
            import mojihen  # type: ignore  # noqa: F401
        except ImportError:
            # Surface as clean error, not traceback
            print(
                "agentgate: ERROR -- cjk check enabled but mojihen is not installed.\n"
                "  Install it with:  pip install agentgate[cjk]\n"
                "  Or disable it:    set [checks] cjk = false in agentgate.toml",
                file=sys.stderr,
            )
            return 2

    try:
        payload_raw = sys.stdin.read()
    except Exception as exc:
        print(f"agentgate hook: failed to read stdin: {exc}", file=sys.stderr)
        return 2

    if not payload_raw or not payload_raw.strip():
        return 0

    # Try JSON parse; non-JSON -> fail open
    try:
        json.loads(payload_raw)
    except (json.JSONDecodeError, ValueError):
        return 0

    from .adapter import from_stdin_json
    from .registry import get_enabled
    from .policy import apply_suppression, decide_block, filter_actionable
    from .report import block_report, warn_report

    event = from_stdin_json(payload_raw)

    if not event.content:
        return 0

    # Run enabled checks
    all_issues = []
    enabled = get_enabled(cfg)
    for name, check_fn in enabled:
        try:
            found = check_fn(event, cfg)
            all_issues.extend(found)
        except RuntimeError as exc:
            # e.g. mojihen missing despite startup check passing (race or monkeypatch)
            print(f"agentgate: ERROR in check '{name}': {exc}", file=sys.stderr)
            return 2

    # Apply suppression
    surviving = apply_suppression(all_issues, event.content, cfg)

    # Filter to actionable (not 'ignore')
    actionable = filter_actionable(surviving, cfg)

    if decide_block(actionable, cfg):
        report = block_report(actionable, file_path=event.file_path)
        print(report, file=sys.stderr)
        return 2

    # Non-blocking warn-level issues: surface to stderr but do not block (exit 0).
    if actionable:
        print(warn_report(actionable, file_path=event.file_path), file=sys.stderr)

    return 0


# ---------------------------------------------------------------------------
# scan subcommand
# ---------------------------------------------------------------------------

def cmd_scan(args: List[str]) -> int:
    """agentgate scan PATH...

    Walk paths, run checks on each file, output in chosen format.

    Exit codes:
      0 = no blocking findings
      1 = blocking findings found
      2 = error
    """
    fmt = "tty"
    config_path: Optional[Path] = None
    paths: List[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--format", "-f") and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        elif arg.startswith("--format="):
            fmt = arg.split("=", 1)[1]
            i += 1
        elif arg in ("--config", "-c") and i + 1 < len(args):
            config_path = Path(args[i + 1])
            i += 2
        elif arg.startswith("--config="):
            config_path = Path(arg.split("=", 1)[1])
            i += 1
        elif arg.startswith("-"):
            print(f"agentgate scan: unknown flag {arg!r}", file=sys.stderr)
            return 2
        else:
            paths.append(arg)
            i += 1

    if not paths:
        print("agentgate scan: no paths specified", file=sys.stderr)
        return 2

    if fmt not in ("tty", "json", "sarif"):
        print(f"agentgate scan: --format must be tty|json|sarif, got {fmt!r}", file=sys.stderr)
        return 2

    cfg = load_config(explicit_path=config_path)

    # Startup dep check
    if cfg.cjk.enabled:
        try:
            import mojihen  # type: ignore  # noqa: F401
        except ImportError:
            print(
                "agentgate: ERROR -- cjk check enabled but mojihen is not installed.\n"
                "  Install it with:  pip install agentgate[cjk]\n"
                "  Or disable it:    set [checks] cjk = false in agentgate.toml",
                file=sys.stderr,
            )
            return 2

    from .adapter import from_stdin_json
    from .model import WriteEvent, Issue
    from .registry import get_enabled
    from .policy import apply_suppression, decide_block, filter_actionable
    from .report import format_tty, format_json, format_sarif
    from .checks.unicode_safety import run as unicode_run

    file_list = collect_files([Path(p) for p in paths])
    if not file_list:
        print(f"agentgate scan: no files found in {paths}", file=sys.stderr)
        return 2

    all_file_issues: List[tuple] = []  # (file_path_str, issue)
    any_blocking = False

    enabled = get_enabled(cfg)

    for fp in file_list:
        source = _read_source(fp)
        if source is None:
            continue

        # Build a synthetic WriteEvent for this file
        event = WriteEvent(
            agent="generic",
            phase="unknown",
            tool="unknown",
            file_path=str(fp),
            content=source,
        )

        file_issues = []
        for name, check_fn in enabled:
            try:
                found = check_fn(event, cfg)
                file_issues.extend(found)
            except RuntimeError as exc:
                print(f"agentgate: ERROR in check '{name}' on {fp}: {exc}", file=sys.stderr)
                return 2

        # Apply suppression
        surviving = apply_suppression(file_issues, source, cfg)
        actionable = filter_actionable(surviving, cfg)

        for issue in actionable:
            all_file_issues.append((str(fp), issue))
            if decide_block([issue], cfg):
                any_blocking = True

    # Render output
    all_issues_flat = [issue for _, issue in all_file_issues]

    if fmt == "json":
        # Build combined JSON with file paths per issue
        import json as _json
        payload = {
            "version": "1",
            "tool": "agentgate",
            "issues": [
                {
                    "check": issue.check,
                    "rule_id": issue.rule_id,
                    "severity": issue.severity,
                    "file": fp_str,
                    "line": issue.line,
                    "col": issue.col,
                    "message": issue.message,
                    "excerpt": issue.excerpt,
                    "suggestion": issue.suggestion,
                }
                for fp_str, issue in all_file_issues
            ],
        }
        _safe_print(_json.dumps(payload, ensure_ascii=False, indent=2))
    elif fmt == "sarif":
        # Build SARIF with file paths
        _print_sarif(all_file_issues)
    else:
        # TTY: group by file
        _print_tty(all_file_issues)

    return 1 if any_blocking else 0


def _print_tty(file_issues: List[tuple]) -> None:
    lines: List[str] = []
    for fp_str, issue in file_issues:
        lines.append(
            f"{fp_str}:{issue.line}:{issue.col}  "
            f"{issue.check}/{issue.rule_id} {issue.severity.upper()}  "
            f"'{issue.excerpt}'"
            + (f"  -> {issue.suggestion}" if issue.suggestion else "")
        )
        lines.append(f"  {issue.message}")

    n = len(file_issues)
    if n == 0:
        lines.append("agentgate: no issues")
    else:
        plural = "issue" if n == 1 else "issues"
        lines.append(f"\nagentgate: {n} {plural}")
    _safe_print("\n".join(lines))


def _print_sarif(file_issues: List[tuple]) -> None:
    import json as _json

    rule_ids_seen = sorted({issue.rule_id for _, issue in file_issues})

    _RULE_DESCRIPTIONS = {
        "AG-BIDI": "Bidi control character that can visually reorder source code (Trojan-Source).",
        "AG-INVIS": "Invisible character inside identifier or string.",
        "AG-HOMO": "Homoglyph: Cyrillic or Greek character that looks like ASCII.",
        "MH001": "Known LLM CJK corruption.",
        "MH002": "Mixed-script token.",
        "MH003": "Isolated CJK in ASCII context.",
    }
    _RULE_NAMES = {
        "AG-BIDI": "bidi-control",
        "AG-INVIS": "invisible-char",
        "AG-HOMO": "homoglyph",
        "MH001": "known-cjk-corruption",
        "MH002": "mixed-script-token",
        "MH003": "isolated-cjk",
    }
    _SARIF_LEVEL = {"high": "error", "medium": "warning", "low": "note"}

    rules = [
        {
            "id": rid,
            "name": _RULE_NAMES.get(rid, rid),
            "shortDescription": {"text": _RULE_DESCRIPTIONS.get(rid, rid)},
            "defaultConfiguration": {"level": "error"},
        }
        for rid in rule_ids_seen
    ]

    results = [
        {
            "ruleId": issue.rule_id,
            "level": _SARIF_LEVEL.get(issue.severity, "warning"),
            "message": {"text": issue.message},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": fp_str},
                        "region": {
                            "startLine": issue.line,
                            "startColumn": issue.col,
                        },
                    }
                }
            ],
        }
        for fp_str, issue in file_issues
    ]

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
    _safe_print(_json.dumps(sarif, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# checks subcommand
# ---------------------------------------------------------------------------

def cmd_checks(args: List[str]) -> int:
    """agentgate checks -- list registered checks, enabled state, and dep status."""
    from .registry import get_all

    config_path: Optional[Path] = None
    for i, arg in enumerate(args):
        if arg in ("--config", "-c") and i + 1 < len(args):
            config_path = Path(args[i + 1])
        elif arg.startswith("--config="):
            config_path = Path(arg.split("=", 1)[1])

    cfg = load_config(explicit_path=config_path)
    registry = get_all()

    print("agentgate checks:")
    print()

    # unicode check
    unicode_enabled = cfg.unicode.enabled
    unicode_status = "enabled" if unicode_enabled else "disabled"
    print(f"  unicode    {unicode_status}  (stdlib, no extra deps)")

    # cjk check
    cjk_enabled = cfg.cjk.enabled
    cjk_status = "enabled" if cjk_enabled else "disabled"
    mojihen_ok = False
    try:
        import mojihen  # type: ignore  # noqa: F401
        mojihen_ok = True
    except ImportError:
        pass

    if cjk_enabled and not mojihen_ok:
        print(f"  cjk        {cjk_status}  [MISSING: mojihen -- run: pip install agentgate[cjk]]")
    elif cjk_enabled and mojihen_ok:
        print(f"  cjk        {cjk_status}  (mojihen installed)")
    else:
        mojihen_note = "(mojihen installed)" if mojihen_ok else "(mojihen not installed)"
        print(f"  cjk        {cjk_status}  {mojihen_note}")

    # Third-party checks
    for name in registry:
        if name not in ("unicode", "cjk"):
            print(f"  {name:<10} enabled  (third-party)")

    print()
    return 0


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def _print_help() -> None:
    msg = (
        "agentgate -- agent-hook safety gate for AI-written code\n\n"
        "Usage:\n"
        "  agentgate hook --stdin                    Hook entrypoint (pipe JSON from agent)\n"
        "  agentgate scan PATH... [--format tty|json|sarif]  Scan files\n"
        "  agentgate checks                          List checks and their status\n"
        "  agentgate --version\n\n"
        "Options:\n"
        "  --config PATH    Explicit config file (agentgate.toml or pyproject.toml)\n"
        "  -h, --help       Show this help\n\n"
        "Exit codes (hook):  0 = allow; 2 = block or error\n"
        "Exit codes (scan):  0 = no blocking issues; 1 = blocking issues; 2 = error\n"
    )
    try:
        print(msg, file=sys.stderr)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    _enable_utf8_io()
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        _print_help()
        return 0 if argv else 2

    if argv[0] == "--version":
        from . import __version__
        print(f"agentgate {__version__}")
        return 0

    from .config import ConfigError
    try:
        if argv[0] == "hook":
            return cmd_hook(argv[1:])

        if argv[0] == "scan":
            return cmd_scan(argv[1:])

        if argv[0] == "checks":
            return cmd_checks(argv[1:])
    except ConfigError as exc:
        print(f"agentgate: config error -- {exc}", file=sys.stderr)
        return 2

    print(f"agentgate: unknown subcommand {argv[0]!r}", file=sys.stderr)
    _print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
