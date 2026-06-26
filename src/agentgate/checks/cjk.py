"""cjk.py -- CJK corruption check using mojihen.

Embeds mojihen.detect.run_detectors per line at cfg.cjk.min_confidence.
Maps mojihen Finding -> agentgate Issue.

If mojihen is not importable AND cjk is enabled, raises RuntimeError with
a clear install message. This error is caught at startup (never silent).
"""

from __future__ import annotations

from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..model import WriteEvent, Issue
    from ..config import GateConfig

from ..model import Issue


def _require_mojihen():
    """Import mojihen and return (run_detectors, Corpus, load_corpus).

    Raises RuntimeError with install instructions if mojihen is absent.
    """
    try:
        from mojihen.detect import run_detectors, CONFIDENCE_RANK  # type: ignore
        from mojihen.corpus import load_corpus  # type: ignore
        return run_detectors, CONFIDENCE_RANK, load_corpus
    except ImportError as exc:
        raise RuntimeError(
            "cjk check enabled but mojihen is not installed.\n"
            "  Install it with:  pip install agentgate[cjk]\n"
            "  Or disable it in config:  [checks]  cjk = false\n"
            f"  (Original error: {exc})"
        ) from exc


def run(event: "WriteEvent", cfg: "GateConfig") -> List["Issue"]:
    """Run CJK corruption check using mojihen. Returns list of Issues."""
    run_detectors, CONFIDENCE_RANK, load_corpus = _require_mojihen()

    content = event.content
    if not content:
        return []

    min_confidence = cfg.cjk.min_confidence

    # Load corpus with defaults
    corpus = load_corpus([])  # empty list = built-in corpus only
    allow_set: set = set()

    issues: List[Issue] = []
    lines = content.splitlines()

    for i, line in enumerate(lines, start=1):
        findings = run_detectors(
            line,
            i,
            corpus,
            allow_set,
            min_confidence=min_confidence,
        )
        for f in findings:
            # Build suggestion from intended list
            suggestion = ""
            if f.intended:
                suggestion = "likely: " + "|".join(f.intended)

            issues.append(Issue(
                check="cjk",
                rule_id=f.rule_id,
                severity="high" if f.confidence == "high" else "medium" if f.confidence == "medium" else "low",
                line=f.line,
                col=f.col,
                message=f.message,
                excerpt=f.run,
                suggestion=suggestion,
            ))

    return issues
