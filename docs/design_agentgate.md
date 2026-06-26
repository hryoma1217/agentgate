# agentgate -- design (v0.3)

> An agent-hook safety gate for AI-written code. Wire it into Claude Code or
> Codex as a hook; it runs a battery of deterministic checks on the text an agent
> is about to write (PreToolUse) or just wrote (PostToolUse) and either blocks the
> write or hands the model a structured "here is what is wrong, rewrite it" signal
> so the loop self-corrects without a human round-trip.

Status: design v0.3 -- revised after two rounds of design review. Source-of-truth
for the build. (Note: this spec is deliberately written
in ASCII punctuation only -- a Unicode-safety tool should not ship a spec with
stray smart-quotes or arrow glyphs; the only non-ASCII characters in this file are
the intentional CJK examples 闾/閾.)

---

## 0. Review history

Round 1 (8 points) and round 2 (3 points), all addressed:

1. Honest enforcement boundary: only PreToolUse can prevent a write (exit 2 denies
   the call). PostToolUse runs after the write and only feeds remediation text
   back to the model; it cannot roll back. See section 3.5.
2. Real Codex adapter: Codex wraps `apply_patch`; the hook payload carries
   `tool_input.command` (the patch envelope), not a tidy `{file_path, content}`.
   The adapter parses `apply_patch` to recover added lines, or limits support when
   it cannot. See section 3.2.
3. Narrowed claim: not "first-in-category." Both agents ship hook frameworks.
   agentgate is a packaged, cross-agent policy + check bundle with an open registry
   and a model-readable feedback contract. See section 1.
4. mojihen dependency resolved: `cjk` requires the `mojihen` package (extra
   `agent-write-gate[cjk]`). Default config has `cjk = false` so the stdlib-only core
   installs and runs out of the box; enabling `cjk` without mojihen is a loud
   startup error, never a silent no-op. See section 4 and 7.
5. Unicode false-positive policy: bidi controls = always high/block. Invisible
   chars are context-sensitive; ZWNJ/ZWJ (U+200C/U+200D) and LRM/RLM
   (U+200E/U+200F) are legitimate in Arabic/Persian/Indic text and emoji ZWJ
   sequences and are NOT flagged by default. See section 3.3.
6. Suppression hardened: only rule-specific suppression
   (`agentgate: ignore[AG-INVIS]`). There is NO bare `agentgate: ignore`. AG-BIDI
   is not suppressible unless config explicitly opts in. See section 3.4.
7. Coverage limits stated. See section 2.1.
8. phantom honesty: M1 ships two built-in checks (cjk, unicode). `phantom`
   (wrapping external `slopcheck`) is an explicit M2 extension. See section 3.3, 8.

Round-2 fixes folded in: (a) `cjk = false` by default (core stays installable);
(b) bare-ignore removed entirely -- suppression is rule-specific only;
(c) the whole spec is ASCII-punctuation-only (no stray Unicode artifacts).

---

## 1. Problem and positioning

AI coding agents now write files directly. They introduce defect classes that
traditional linters/CI were not built to catch, and that surface only after the
text is written, committed, sometimes pushed:

- valid-but-wrong CJK -- a real but wrong kanji/hanzi/hangul (mojihen's domain;
  grep + unit tests pass it as false-green).
- bidi / invisible Unicode -- Trojan-Source bidi overrides and invisible chars
  smuggled into source.

Both have standalone CLIs that run in CI. What is missing is a single hook at the
agent write boundary that (a) speaks the agents' hook protocols, (b) applies one
severity-to-action policy across checks, and (c) returns a model-readable feedback
blob so the agent rewrites itself.

Positioning (honest): agentgate is not a new category -- Claude Code and Codex
already expose hook frameworks. agentgate is the packaged, cross-agent gate that
bundles the AI-write-specific checks, normalizes the two agents' payloads,
centralizes block/warn policy, and ships an open check registry so the set grows
without forking. The ecosystem value is the gate + registry standard, plus
composing the sibling engine mojihen, not any single linter.

---

## 2. Non-goals

- Not a general SAST / secret scanner / dependency auditor (those run in CI).
- Not a network service. Offline + deterministic by default (mojihen's ethos).
- Not a reimplementation of slopcheck / bidichk / semgrep. Richer external tools
  are wrapped when present (M2); built-ins stay minimal and offline.

### 2.1 Coverage limits (stated honestly)

agentgate only sees writes that flow through a hooked tool call. It does NOT see,
and makes no claim about:

- files written by shell commands the agent runs (`echo >`, `sed -i`, codegen);
- pre-existing files, generated artifacts, or out-of-band edits;
- editor/IDE agents that do not emit the supported hook payloads;
- Codex tool paths other than `apply_patch` (best-effort; fail-open otherwise);
- anything a PostToolUse hook is asked to undo -- it cannot roll back a completed
  write, only report it back to the model.

These limits are documented in the README so adopters do not over-trust the gate.

---

## 3. Architecture

```
agent hook event (stdin JSON)
        |
        v
 +--------------+  normalize per-agent payload -> WriteEvent
 |  adapter     |  {agent, phase, tool, file_path, content}
 +------+-------+
        v
 +--------------+  for each enabled check: run(event,cfg) -> [Issue]
 |  registry    |  builtin: cjk (needs mojihen), unicode (stdlib)
 +------+-------+
        v
 +--------------+  severity -> action via policy; rule-specific suppression
 |  policy      |
 +------+-------+
        v
 decision: PreToolUse  -> exit 2 = DENY write
           PostToolUse -> exit 2 = feedback (no rollback)
           exit 0 = allow
```

### 3.1 Data model

```python
@dataclass
class WriteEvent:
    agent: str        # "claude-code" | "codex" | "generic"
    phase: str        # "pre" | "post" | "unknown"
    tool: str         # "Write" | "Edit" | "apply_patch" | "unknown"
    file_path: str    # best-effort; "<stdin>" if absent
    content: str      # the added/written text to inspect

@dataclass
class Issue:
    check: str        # "cjk" | "unicode"
    rule_id: str      # "MH001" | "AG-BIDI" | "AG-INVIS" | "AG-HOMO"
    severity: str     # "high" | "medium" | "low"
    line: int
    col: int
    message: str
    excerpt: str
    suggestion: str = ""
```

### 3.2 Adapter (protocol normalization)

Single JSON object on stdin. Tolerant extraction; `phase`/`agent` inferred from the
payload's own fields (inference only affects the decision dialect in 3.5, never
check behavior).

Claude Code (`hook_event_name` = `PreToolUse` | `PostToolUse`):
`{hook_event_name, tool_name, tool_input:{file_path, content|new_string}}`.
-> agent=claude-code, phase from hook_event_name, tool from tool_name, content from
`content` (Write) or `new_string` (Edit).

Codex (wraps `apply_patch`): payload exposes `tool_input.command` containing an
`apply_patch` envelope (the `*** Begin Patch` / `*** Add File:` / `*** Update File:`
/ `+`-prefixed add lines / `*** End Patch` form). The adapter:
1. locates the `apply_patch` body in `command` (string or argv list),
2. parses it, collecting added lines (lines starting with `+`, excluding any `+++`
   header) and the target path from `*** Add File:` / `*** Update File:`,
3. joins added lines as `content`.
If the envelope cannot be parsed -> WriteEvent with empty content and tool=unknown
(gate fails open; see 2.1). Codex support is explicit and bounded to `apply_patch`.

Generic / fallback: top-level `{file_path|path, content|text|new_string}`; the
top-level object may itself be the tool_input. agent=generic, phase=unknown.

Empty extractable text -> exit 0 (nothing to gate). Non-JSON stdin -> exit 0
(fail-open; the gate must never wedge an agent on malformed input).

### 3.3 Checks (registry)

`def run(event: WriteEvent, cfg) -> List[Issue]`, registered by name.

cjk (built-in; requires `mojihen`): embeds `mojihen.detect.run_detectors` per line
at `min_confidence` (default high); maps Finding -> Issue (suggestion = "likely:
..."). Default config has `cjk = false`. If `cjk` is enabled but `mojihen` is not
importable -> the gate raises a startup error ("cjk check enabled but mojihen not
installed; `pip install agent-write-gate[cjk]` or disable [checks].cjk"). Never silent.

unicode (built-in; stdlib only): minimal membership tests, not a port of a big
tool. Context-sensitive to control false positives:

- AG-BIDI (high, always block, not suppressible by default): bidi controls
  U+202A-U+202E, U+2066-U+2069. Essentially no legitimate use in source.
- AG-INVIS (high in code context, off in prose): zero-width and invisible chars
  U+200B, U+2060, U+FEFF (when not the offset-0 BOM), U+00AD (soft hyphen). Flagged
  only when the file is treated as code (by extension; see below) and the char sits
  inside an identifier/string run. U+200C/U+200D (ZWNJ/ZWJ) and U+200E/U+200F
  (LRM/RLM) are NOT in AG-INVIS by default -- legitimate in Arabic/Persian/Indic
  text and emoji ZWJ sequences. A strict opt-in (`unicode.strict_zerowidth = true`)
  adds ZWNJ/ZWJ only inside ASCII-identifier runs (never CJK/RTL/emoji context).
- AG-HOMO (medium, opt-in `unicode.homoglyph = true`): Latin-looking
  Cyrillic/Greek codepoints inside an otherwise-ASCII identifier (reuses mojihen's
  MH002 idea). Off by default.

File-type policy: extensions in `code_extensions` (default: common source) get the
code defaults; everything else (.md, .txt, localization, prose) gets the doc
profile where AG-INVIS is off and only AG-BIDI applies. When `file_path` is
unknown, default to the doc (permissive) profile to avoid false positives, except
AG-BIDI which always applies.

phantom -- NOT in M1. Documented M2 extension that shells out to an external
`slopcheck`-style binary only if present; agentgate never bundles or reimplements
it.

Registry is open: `register(name, fn)`; built-ins registered at import -- the
extension point for third-party checks.

### 3.4 Policy (severity -> action) + suppression

```toml
[policy]
high   = "block"
medium = "warn"
low    = "ignore"
```

A write is blocked iff any issue maps to `block`. Per-check `severity_floor`
allowed.

Suppression (hardened): only rule-specific directives are honored --
`agentgate: ignore[AG-INVIS]` on the offending line skips that rule for that line.
There is no bare `agentgate: ignore`. AG-BIDI is not suppressible unless
`[checks.unicode] allow_bidi_suppression = true` is set explicitly (off by
default) -- Trojan-Source controls must not be launderable by a same-line comment
the model can emit.

### 3.5 Decision and feedback contract (per phase)

The decision dialect depends on `phase`:

- PreToolUse (true prevention):
  - block -> exit 2: Claude Code denies the tool call and shows stderr to the
    model; Codex (PreToolUse around apply_patch) likewise rejects. Only path that
    prevents the write.
  - allow -> exit 0.
- PostToolUse (remediation only -- the write already happened):
  - block -> exit 2: stderr is surfaced to the model as feedback so it issues a
    corrective follow-up write. Does NOT undo the prior write.
  - allow -> exit 0.
- unknown phase (generic adapter): treat as PostToolUse semantics (feedback).

Block report on stderr is model-readable:

```
agentgate: BLOCKED -- 2 issue(s) to fix before this write

  app.py:3:18  cjk/MH001 HIGH  '闾'  -> likely: 閾
      Valid-but-wrong kanji. Replace 闾 (U+95FE) with 閾.
  app.py:5:1   unicode/AG-BIDI HIGH  U+202E RIGHT-TO-LEFT OVERRIDE
      Remove the bidi control char; it visually reorders source.

  Fix these and re-emit.
```

### 3.6 CLI surface

```
agentgate hook --stdin     # primary: agent hook entrypoint (Pre/PostToolUse)
agentgate scan PATH...      # same checks over files (CI / manual); tty|json|sarif
agentgate checks            # list checks + enabled/disabled + missing deps
agentgate --version
```

`scan` exit codes: 0 = no blocking findings; 1 = blocking findings.
`hook` exit codes: 0 = allow; 2 = block (deny in Pre / feedback in Post) or usage.

`_enable_utf8_io()` at startup (Windows cp932) -- same fix proven in mojihen.

---

## 4. Config and packaging

`agentgate.toml` or `[tool.agentgate]` in `pyproject.toml`. `tomllib` on 3.11+,
graceful default otherwise.

```toml
[checks]
cjk     = false           # default off so stdlib core installs+runs; enable with agent-write-gate[cjk]
unicode = true

[checks.cjk]
min_confidence = "high"

[checks.unicode]
homoglyph = false
strict_zerowidth = false
allow_bidi_suppression = false
code_extensions = [".py",".js",".ts",".go",".rs",".java",".c",".cpp",".rb",".php",".sh",".sql"]

[policy]
high = "block"
medium = "warn"
low = "ignore"
```

Packaging: core install (`pip install agent-write-gate`) = stdlib-only, ships
adapter/registry/policy/unicode + CLI and works with the default config. `pip
install agent-write-gate[cjk]` pulls in `mojihen`; then set `cjk = true`. Separate PyPI
packages so each is independently adoptable.

---

## 5. Layout

```
agentgate/
  pyproject.toml            # [project.optional-dependencies] cjk = ["mojihen>=0.1"]
  README.md
  docs/design_agentgate.md
  src/agentgate/
    __init__.py
    cli.py                  # arg parse, subcommands, _enable_utf8_io, startup dep-check
    adapter.py              # stdin JSON -> WriteEvent (claude-code / codex apply_patch / generic)
    apply_patch.py          # parse apply_patch envelope -> added lines + path
    model.py                # WriteEvent, Issue
    registry.py             # register/get; builtin registration
    policy.py               # severity->action, rule-specific suppression, bidi lock
    config.py               # load agentgate.toml / pyproject; defaults
    report.py               # block report (stderr) + scan tty/json/sarif
    checks/
      __init__.py
      cjk.py                # embeds mojihen; hard-error if enabled+missing
      unicode_safety.py     # AG-BIDI / AG-INVIS (context) / AG-HOMO (opt-in)
  hooks/
    claude-code.md          # PreToolUse (block) + PostToolUse (feedback) setups
    codex.md                # apply_patch PreToolUse/PostToolUse setup + limits
  .pre-commit-hooks.yaml    # `agentgate scan`
  tests/
    test_adapter.py            # claude-code + codex apply_patch + generic -> WriteEvent
    test_apply_patch.py        # add/update/multi-hunk parsing; unparsable -> fail-open
    test_unicode_check.py      # bidi/invis positives
    test_unicode_falsepos.py   # Arabic/Persian/Hindi ZWNJ, emoji ZWJ, BOM@0, prose -> clean
    test_policy.py             # severity->action, rule-specific suppression, bidi not suppressible
    test_hook_exit.py          # pre-block=2, post-block=2, allow=0, non-json=0, empty=0
    test_scan.py               # scan fixtures; json/sarif validity
    test_cjk_integration.py    # mojihen present -> MH001 blocks; enabled+absent -> startup error
    fixtures/
```

---

## 6. Tests / quality gates

- adapter: all three payload shapes normalize; Codex apply_patch yields added lines
  + path; unparsable apply_patch -> empty content (fail-open).
- unicode positives: each bidi control + each in-code invisible flagged at correct
  line/col.
- unicode false-positive gate (critical): Arabic/Persian text with ZWNJ, Hindi with
  ZWJ, emoji ZWJ sequences, a BOM at offset 0, and ordinary Markdown prose all
  yield zero issues under default policy. Legit CJK/emoji clean.
- policy: high->block->exit2; medium->warn->exit0; rule-specific suppression works;
  AG-BIDI not silenced unless allow_bidi_suppression set.
- hook exit codes: pre-block=2, post-block=2, allow=0, non-JSON=0, empty=0.
- cjk integration: mojihen present -> corrupt line blocks via MH001; cjk enabled
  with mojihen monkeypatched absent -> startup error (not silent).
- self-contained core: full suite green with only stdlib for non-cjk tests; cjk
  integration test skips cleanly if mojihen not installed.

---

## 7. Relationship to mojihen

mojihen = the CJK engine (its own PyPI package, independently useful). agentgate =
the cross-agent gate that composes it (optional extra `agent-write-gate[cjk]`) with the
stdlib Unicode-safety check, under one policy and one model-readable feedback
contract. The `cjk` check is a hard (loud) dependency when enabled -- never a
silent no-op; default config leaves it off so the core installs clean. Two focused
packages; the gate + open registry is the ecosystem layer.

---

## 8. Milestones

- M1 (this build): adapter (claude-code + codex apply_patch + generic) +
  apply_patch parser + model + registry + policy (hardened suppression) + config +
  cjk (mojihen) + unicode checks + hook/scan/checks CLI + full test suite (incl.
  multilingual false-positive gate) + README + hook docs. Two built-in checks.
  Shippable unit.
- M2: phantom external wrapper (slopcheck), homoglyph hardening, richer
  external-tool wrappers.
- M3: Cursor / Aider adapters, plugin docs for `register`, SARIF polish.
