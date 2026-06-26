"""registry.py -- Check registry for agentgate.

Built-in checks are registered at import time.
Third-party checks can be added via register(name, fn).

A check function has signature:
  def run(event: WriteEvent, cfg: GateConfig) -> List[Issue]: ...
"""

from __future__ import annotations

from typing import Callable, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .model import WriteEvent, Issue
    from .config import GateConfig

# ---------------------------------------------------------------------------
# Registry storage
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, Callable] = {}


def register(name: str, fn: Callable) -> None:
    """Register a check function under the given name."""
    _REGISTRY[name] = fn


def get_enabled(cfg: "GateConfig") -> List[tuple]:
    """Return list of (name, fn) pairs for all enabled checks."""
    enabled = []
    if cfg.unicode.enabled and "unicode" in _REGISTRY:
        enabled.append(("unicode", _REGISTRY["unicode"]))
    if cfg.cjk.enabled and "cjk" in _REGISTRY:
        enabled.append(("cjk", _REGISTRY["cjk"]))
    # Any additional registered checks (third-party)
    for name, fn in _REGISTRY.items():
        if name not in ("unicode", "cjk"):
            enabled.append((name, fn))
    return enabled


def get_all() -> Dict[str, Callable]:
    """Return a copy of the full registry."""
    return dict(_REGISTRY)


# ---------------------------------------------------------------------------
# Register built-ins at import time
# ---------------------------------------------------------------------------

def _register_builtins() -> None:
    from .checks.unicode_safety import run as unicode_run
    register("unicode", unicode_run)

    from .checks.cjk import run as cjk_run
    register("cjk", cjk_run)


_register_builtins()
