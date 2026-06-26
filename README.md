# agentgate

An agent-hook safety gate for AI-written code. Wire it into Claude Code or Codex
as a hook; it runs a battery of deterministic checks on the text an agent is about
to write (PreToolUse) or just wrote (PostToolUse) and either blocks the write or
hands the model a structured feedback blob so the loop self-corrects without a
human round-trip.

## Problem

AI coding agents write files directly. They introduce defect classes that
traditional linters and CI were not built to catch:

- **Valid-but-wrong CJK** -- a real but wrong kanji/hanzi/hangul (mojihen's
  domain; grep and unit tests pass it as false-green).
- **Bidi / invisible Unicode** -- Trojan-Source bidi overrides and invisible
  characters smuggled into source identifiers.

Both have standalone CLIs that run in CI. What is missing is a single hook at
the agent write boundary that (a) speaks the agents' hook protocols, (b) applies
one severity-to-action policy across checks, and (c) returns a model-readable
feedback blob so the agent rewrites itself.

## Positioning (honest)

agentgate is not a new category -- Claude Code and Codex already expose hook
frameworks. agentgate is the packaged, cross-agent gate that bundles
AI-write-specific checks, normalizes the two agents' payloads, centralizes
block/warn policy, and ships an open check registry so the set grows without
forking. The ecosystem value is the gate + registry standard, plus composing the
sibling engine mojihen, not any single linter.

## Coverage limits

agentgate only sees writes that flow through a hooked tool call. It does NOT see,
and makes no claim about:

- Files written by shell commands the agent runs (`echo >`, `sed -i`, codegen).
- Pre-existing files, generated artifacts, or out-of-band edits.
- Editor/IDE agents that do not emit the supported hook payloads.
- Codex tool paths other than `apply_patch` (best-effort; fail-open otherwise).
- Anything a PostToolUse hook is asked to undo -- it cannot roll back a completed
  write, only report it back to the model.

## M1 built-in checks

### unicode (stdlib, always available)

- **AG-BIDI** (high, always block): bidi control characters U+202A-U+202E,
  U+2066-U+2069. These are the Trojan-Source vectors with essentially no
  legitimate use in source files.
- **AG-INVIS** (high, code context only): invisible chars (U+200B zero-width
  space, U+2060 word joiner, U+FEFF stray BOM, U+00AD soft hyphen) flagged only
  when the file has a code extension AND the char is inside an identifier/string
  run. U+200C/U+200D (ZWNJ/ZWJ) and U+200E/U+200F (LRM/RLM) are NOT flagged
  by default -- they are legitimate in Arabic/Persian/Indic text and emoji ZWJ
  sequences. Strict mode (`unicode.strict_zerowidth = true`) adds ZWNJ/ZWJ only
  inside ASCII-identifier runs.
- **AG-HOMO** (medium, opt-in): Latin-looking Cyrillic/Greek codepoints inside
  an otherwise-ASCII identifier. Off by default.

### cjk (requires mojihen extra)

Embeds `mojihen.detect.run_detectors` to catch known LLM CJK corruption: a
real but wrong kanji/hanzi that grep and unit tests pass as false-green (rule
MH001 and others). Disabled by default so the stdlib-only core installs and runs
out of the box.

## Install

Core (stdlib-only, unicode check):

```sh
pip install agent-write-gate
```

With CJK check (requires mojihen):

```sh
pip install agent-write-gate[cjk]
```

Then enable in config:

```toml
# agentgate.toml
[checks]
cjk = true
```

## CLI

```sh
# Primary: agent hook entrypoint (pipe JSON from agent hook system)
agentgate hook --stdin

# Scan files (CI / manual audit)
agentgate scan src/ --format tty|json|sarif

# List checks and their status
agentgate checks

# Version
agentgate --version
```

Exit codes:
- `hook`: 0 = allow; 2 = block (deny in Pre / feedback in Post) or error.
- `scan`: 0 = no blocking findings; 1 = blocking findings; 2 = error.

## Hook setup: Claude Code

Add to `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{"type": "command", "command": "agentgate hook --stdin"}]
      }
    ]
  }
}
```

**PreToolUse** (exit 2) denies the tool call -- the write never happens.
**PostToolUse** (exit 2) surfaces feedback to the model after the write.
Only PreToolUse provides true prevention. See `hooks/claude-code.md`.

## Hook setup: Codex

Only `apply_patch` is supported (Codex's primary write tool):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "apply_patch",
        "hooks": [{"type": "command", "command": "agentgate hook --stdin"}]
      }
    ]
  }
}
```

See `hooks/codex.md` for PostToolUse setup and coverage limits.

## pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/hryoma1217/agentgate
    rev: v0.1.0
    hooks:
      - id: agentgate
```

The bidi / invisible-Unicode checks work out of the box. The CJK corruption
check is **off by default**; if you enable it (`[checks.cjk] enabled = true`), the
hook also needs `mojihen` in pre-commit's isolated env — add it via
`additional_dependencies`:

```yaml
      - id: agentgate
        additional_dependencies: ["agent-write-gate[cjk]"]
```

## Configuration

`agentgate.toml` or `[tool.agentgate]` in `pyproject.toml`. Falls back to
defaults when no config file is found.

```toml
# Unicode checks are ON by default; the CJK check is OFF by default.
# Enable CJK only if you installed the `agent-write-gate[cjk]` extra.
[checks.cjk]
enabled        = false
min_confidence = "high"

[checks.unicode]
enabled                = true
homoglyph              = false
strict_zerowidth       = false
allow_bidi_suppression = false
code_extensions = [
  ".py", ".js", ".ts", ".go", ".rs", ".java",
  ".c", ".cpp", ".rb", ".php", ".sh", ".sql"
]

[policy]
high   = "block"
medium = "warn"
low    = "ignore"
```

## Suppression

Rule-specific only: `agentgate: ignore[AG-INVIS]` on the offending line.
**There is no bare `agentgate: ignore`** -- that would let a model launder
violations. AG-BIDI is not suppressible unless `allow_bidi_suppression = true`.

## Model-readable block report

When a write is blocked, stderr looks like:

```
agentgate: BLOCKED -- 2 issue(s) to fix before this write

  app.py:3:18  cjk/MH001 HIGH  '闾'  -> likely: 閾
      '闾' is a known LLM corruption (likely intended: 閾) ...
  app.py:5:1   unicode/AG-BIDI HIGH  U+202E RIGHT-TO-LEFT OVERRIDE
      Remove the bidi control char; it visually reorders source.

  Fix these and re-emit.
```

The model sees this as a structured remediation signal and issues a corrective
write without human intervention.

## Relationship to mojihen

mojihen is the CJK engine (its own PyPI package, independently useful).
agentgate is the cross-agent gate that composes it (optional extra
`agent-write-gate[cjk]`) with the stdlib Unicode-safety check, under one policy and
one model-readable feedback contract. Two focused packages; the gate + open
registry is the ecosystem layer.

## Open registry

Third-party checks can be registered:

```python
from agentgate.registry import register

def my_check(event, cfg):
    # event: WriteEvent, cfg: GateConfig
    # return List[Issue]
    return []

register("my-check", my_check)
```

## License

MIT
