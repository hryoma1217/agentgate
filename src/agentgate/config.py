"""config.py -- Load agentgate configuration.

Looks for config in order:
  1. Explicit path (--config flag)
  2. agentgate.toml in current directory
  3. [tool.agentgate] in pyproject.toml in current directory
  4. Built-in defaults

Uses tomllib (Python 3.11+) when available; falls back to defaults on older
Python (a minimal TOML subset parser is NOT implemented -- just use defaults).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Default values (mirrors section 4 of the design doc)
# ---------------------------------------------------------------------------

_DEFAULT_CODE_EXTENSIONS = [
    ".py", ".js", ".ts", ".go", ".rs", ".java",
    ".c", ".cpp", ".rb", ".php", ".sh", ".sql",
]


@dataclass
class PolicyConfig:
    high: str = "block"
    medium: str = "warn"
    low: str = "ignore"


@dataclass
class CjkConfig:
    enabled: bool = False
    min_confidence: str = "high"


@dataclass
class UnicodeConfig:
    enabled: bool = True
    homoglyph: bool = False
    strict_zerowidth: bool = False
    allow_bidi_suppression: bool = False
    code_extensions: List[str] = field(default_factory=lambda: list(_DEFAULT_CODE_EXTENSIONS))


@dataclass
class GateConfig:
    cjk: CjkConfig = field(default_factory=CjkConfig)
    unicode: UnicodeConfig = field(default_factory=UnicodeConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)


# ---------------------------------------------------------------------------
# TOML loading (stdlib tomllib on 3.11+; graceful default otherwise)
# ---------------------------------------------------------------------------

class ConfigError(Exception):
    """Raised when a config file exists but cannot be parsed."""


def _load_toml(path: Path) -> Optional[Dict[str, Any]]:
    """Load a TOML file.

    Returns None if the file is absent. Raises ConfigError if the file exists
    but cannot be parsed (so a broken config is never silently ignored).
    """
    if not path.exists():
        return None

    if sys.version_info >= (3, 11):
        import tomllib as _toml  # type: ignore
        decode_error = _toml.TOMLDecodeError
    else:
        try:
            import tomli as _toml  # type: ignore
        except ImportError as exc:  # pragma: no cover - tomli is a declared dep
            raise ConfigError(
                f"{path}: parsing TOML on Python < 3.11 requires the 'tomli' "
                "package (install agent-write-gate, which depends on it)."
            ) from exc
        decode_error = _toml.TOMLDecodeError

    try:
        with open(path, "rb") as fh:
            return _toml.load(fh)
    except decode_error as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------

def _apply_dict(cfg: GateConfig, d: Dict[str, Any]) -> None:
    """Apply a parsed TOML dict onto a GateConfig (mutates in place)."""
    checks = d.get("checks", {})
    if isinstance(checks, dict):
        # Top-level boolean toggles
        if "cjk" in checks and isinstance(checks["cjk"], bool):
            cfg.cjk.enabled = checks["cjk"]
        if "unicode" in checks and isinstance(checks["unicode"], bool):
            cfg.unicode.enabled = checks["unicode"]

        # Nested [checks.cjk]
        cjk_sub = checks.get("cjk")
        if isinstance(cjk_sub, dict):
            cfg.cjk.enabled = True  # sub-table presence implies enabled
            if "enabled" in cjk_sub:
                cfg.cjk.enabled = bool(cjk_sub["enabled"])
            if "min_confidence" in cjk_sub:
                cfg.cjk.min_confidence = str(cjk_sub["min_confidence"])

        # Nested [checks.unicode]
        uni_sub = checks.get("unicode")
        if isinstance(uni_sub, dict):
            if "enabled" in uni_sub:
                cfg.unicode.enabled = bool(uni_sub["enabled"])
            if "homoglyph" in uni_sub:
                cfg.unicode.homoglyph = bool(uni_sub["homoglyph"])
            if "strict_zerowidth" in uni_sub:
                cfg.unicode.strict_zerowidth = bool(uni_sub["strict_zerowidth"])
            if "allow_bidi_suppression" in uni_sub:
                cfg.unicode.allow_bidi_suppression = bool(uni_sub["allow_bidi_suppression"])
            if "code_extensions" in uni_sub and isinstance(uni_sub["code_extensions"], list):
                cfg.unicode.code_extensions = list(uni_sub["code_extensions"])

    policy = d.get("policy", {})
    if isinstance(policy, dict):
        if "high" in policy:
            cfg.policy.high = str(policy["high"])
        if "medium" in policy:
            cfg.policy.medium = str(policy["medium"])
        if "low" in policy:
            cfg.policy.low = str(policy["low"])


def load_config(explicit_path: Optional[Path] = None) -> GateConfig:
    """Load configuration, returning GateConfig with defaults for any missing keys."""
    cfg = GateConfig()

    raw: Optional[Dict[str, Any]] = None

    if explicit_path is not None:
        raw = _load_toml(explicit_path)
        if raw is not None:
            _apply_dict(cfg, raw)
        return cfg

    # Try agentgate.toml
    ag_toml = Path("agentgate.toml")
    raw = _load_toml(ag_toml)
    if raw is not None:
        _apply_dict(cfg, raw)
        return cfg

    # Try [tool.agentgate] in pyproject.toml
    pyproject = Path("pyproject.toml")
    raw = _load_toml(pyproject)
    if raw is not None:
        tool_section = raw.get("tool", {}).get("agentgate")
        if isinstance(tool_section, dict):
            _apply_dict(cfg, tool_section)

    return cfg
