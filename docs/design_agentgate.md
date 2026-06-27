# agentgate -- design (v0.4)

> An agent-hook safety gate for AI-written code. Wire it into Claude Code or
> Codex as a hook; it runs a battery of deterministic checks on the text an agent
> is about to write (PreToolUse) or just wrote (PostToolUse) and either blocks the
> write or hands the model a structured "here is what is wrong, rewrite it" signal
> so the loop self-corrects without a human round-trip.

Status: design v0.4 -- revised after two rounds of design review AND a round of
empirical verification against a real `codex-cli 0.141.0` hook run (see section 0.1
and section 3.5). The v0.3 Codex assumptions were wrong on two points; v0.4 records
the measured behavior and the corrected contract. Source-of-truth for the build.
(Note: this spec is deliberately written in ASCII punctuation only -- a
Unicode-safety tool should not ship a spec with stray smart-quotes or arrow glyphs;
the only non-ASCII characters in this file are the intentional CJK examples 闾/閾.)

---

## 0. Review history

Round 1 (8 points) and round 2 (3 points), all addressed:

1. Honest enforcement boundary: only PreToolUse can prevent a write (Claude: exit 2
   denies the call; Codex: a stdout `permissionDecision:"deny"` JSON with exit 0 --
   see 0.1.3 and 3.5). PostToolUse runs after the write and cannot roll back; it
   only feeds remediation text back to the model on Claude (exit 2 + stderr). On
   Codex the model-facing PostToolUse remediation channel is UNVERIFIED on 0.141.0,
   so agentgate treats Codex Post as logging-only (stderr + exit 0). See section 3.5.
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

### 0.1 Round 3 -- empirical verification (codex-cli 0.141.0)

v0.3 was written against documented/third-party descriptions of Codex hooks. A real
`codex exec` run with a logging hook injected ephemerally via `-c` (config.toml
never written; `--ignore-user-config` so the user's config is not loaded;
`--dangerously-bypass-hook-trust` to run the injected hook) measured the actual
behavior. Three findings, two of which CONTRADICT v0.3:

1. apply_patch DOES fire PreToolUse and PostToolUse (v0.3 hedged "best-effort").
   The earlier worry that apply_patch may not emit PreToolUse is false for 0.141.0.

2. Real Codex PreToolUse payload for apply_patch (CONFIRMED shape):
   ```json
   {"session_id","turn_id","transcript_path","cwd","hook_event_name":"PreToolUse",
    "model","permission_mode","tool_name":"apply_patch",
    "tool_input":{"command":"*** Begin Patch\n*** Add File: greeting.txt\n+...\n*** End Patch"},
    "tool_use_id":"exec-<uuid>"}
   ```
   It carries BOTH `hook_event_name` AND `tool_name` (just like Claude Code), but
   `tool_input` holds only `command`, not `{file_path, content}`. PostToolUse adds
   `tool_response`. => v0.3's adapter routing (section 3.2) had a latent bug: the
   "has hook_event_name + tool_name -> claude-code, extract content/new_string"
   branch fires FIRST and finds no content in `{command}`, returning empty => the
   gate exits 0 (fail-open) and never reaches the apply_patch parser. Codex
   corruption was being MISSED. v0.4 section 3.2 reorders detection.

3. Block mechanism (CONFIRMED by measuring whether the file got written):
   | hook returns                                              | Codex result          |
   |----------------------------------------------------------|-----------------------|
   | stdout JSON permissionDecision="deny", exit 0            | BLOCKS (no write)     |
   | legacy stdout {"decision":"block","reason":...}, exit 0  | BLOCKS (no write)     |
   | stderr + exit 2                                           | "hook Failed" -> WRITE PROCEEDS (fail-open) |
   | stdout JSON deny + exit 2                                 | "hook Failed" -> WRITE PROCEEDS |
   => For Codex, exit code 2 is treated as a hook *failure* (fail-open), NOT a
   block. The ONLY way to deny a Codex apply_patch is stdout JSON
   `permissionDecision:"deny"` with **exit 0**. This DIRECTLY contradicts v0.3
   section 3.5 ("Codex ... exit 2 ... likewise rejects"). Claude Code, by contrast,
   blocks on exit 2 + stderr. The contract must therefore be agent-aware.

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
- per-file attribution inside a MULTI-file `apply_patch`: M1 collapses all added
  lines into one `content` and reports the FIRST target path. The checks still run
  over every added line (a corrupt char in any file is caught), but the reported
  `file_path` and the code-vs-prose profile are taken from the first file only.
  Per-hunk attribution is an M2 refinement (see 3.2);
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
 decision: Claude PreToolUse  -> exit 2 + stderr = DENY write
           Codex  PreToolUse  -> stdout JSON permissionDecision:deny + exit 0 = DENY
           PostToolUse        -> feedback only (no rollback)
           allow              -> exit 0
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

Detection ORDER matters (this is the v0.4 fix; see 0.1.2). Both Claude Code and
Codex send `hook_event_name` + `tool_name`, so the adapter must NOT route on the
mere presence of those two fields. It routes on the tool identity / payload shape:

1. apply_patch FIRST. If `tool_name == "apply_patch"`, OR `tool_input.command`
   (string or argv list) contains an `apply_patch` envelope (`*** Begin Patch`),
   treat it as Codex:
   - parse the envelope, collecting added lines (lines starting with `+`, excluding
     any `+++` header) and the target path from `*** Add File:` / `*** Update File:`,
   - join added lines as `content`; agent=codex, tool=apply_patch, phase from
     `hook_event_name`.
   - If the envelope cannot be parsed -> empty content (gate fails open; see 2.1).
   Codex support is explicit and bounded to `apply_patch`. M1 limitation: a
   multi-file patch is collapsed to one `content` (all added lines) and the FIRST
   target path -- every added line is still scanned, but `file_path` and the
   code/prose profile come from the first file only. Per-hunk WriteEvent emission is
   deferred to M2 (noted in 2.1).

2. Claude Code NEXT. Else if `hook_event_name` + `tool_name` are present (Write,
   Edit, ...): agent=claude-code, phase from hook_event_name, tool from tool_name,
   content from `content` (Write) or `new_string` (Edit), path from `file_path`.

3. Generic / fallback. Top-level `{file_path|path, content|text|new_string}`; the
   top-level object may itself be the tool_input. agent=generic, phase=unknown.

(Rationale: the confirmed Codex payload (0.1.2) has `tool_name:"apply_patch"` AND
`hook_event_name`. The old "hook_event_name && tool_name -> claude-code" first
branch swallowed it and extracted no content -> fail-open miss. Checking
apply_patch first closes that hole.)

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

The decision dialect depends on BOTH `phase` and `agent` (the two agents disagree
on what a block looks like -- see 0.1.3, measured on codex-cli 0.141.0):

- PreToolUse block (true prevention):
  - Claude Code (agent=claude-code): write block report to stderr, `exit 2`.
    Claude denies the tool call and feeds stderr to the model. (unchanged)
  - Codex (agent=codex): print a single JSON object to **stdout** and `exit 0`:
    ```json
    {"hookSpecificOutput":{"hookEventName":"PreToolUse",
      "permissionDecision":"deny","permissionDecisionReason":"<block report>"}}
    ```
    The block report is ALSO written to stderr (for humans / logs), but the
    machine-actionable deny is the stdout JSON. exit 0 is mandatory: Codex treats a
    non-zero hook exit as a *failure* and lets the write through (fail-open). stdout
    must contain ONLY the JSON object (cmd_hook prints everything else to stderr).
  - generic / unknown agent, and the `phase=unknown` case (generic adapter, 3.2):
    keep the Claude dialect (stderr block report + exit 2). A real Codex apply_patch
    is detected as agent=codex by 3.2 and gets the JSON path; for truly-unknown
    inputs exit 2 is the conservative default that blocks Claude-like consumers (and
    is a harmless no-op fail-open on Codex, which is already the documented caveat
    for non-detected Codex paths -- see 2.1). So a blocking finding with unknown
    phase is ALWAYS surfaced (stderr + exit 2), never silently dropped.
- PostToolUse (remediation only -- the write already happened, no rollback):
  - block -> write the block report to stderr; `exit 2` for Claude (Claude surfaces
    stderr to the model as feedback). For Codex, PostToolUse cannot prevent or undo
    the write and the model-facing remediation channel is UNVERIFIED on 0.141.0
    (only PreToolUse denial was measured); agentgate therefore treats Codex Post as
    logging-only: write the report to stderr, `exit 0` (exit 2 is just a logged hook
    failure on Codex, not feedback). Either way the prior write stands.
  - allow -> exit 0.
- warn-level (actionable but mapped to `warn`, not `block`, any agent/phase): the
  warn report is ALWAYS written to stderr (never suppressed), nothing on stdout,
  exit 0. allow (no actionable issues): nothing on stdout/stderr, exit 0.

The block JSON deny is scoped to PreToolUse, the only phase where it can actually
prevent the write.

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
`hook` exit codes: 0 = allow OR Codex deny-via-stdout-JSON; 2 = Claude block
(deny in Pre / feedback in Post) or usage error. (The exit code is agent-aware: a
Codex apply_patch block is exit 0 with a stdout deny JSON; see 3.5.)

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
    test_hook_exit.py          # Claude pre/post-block=2; Codex pre-block=exit0+stdout deny JSON; allow=0, non-json=0, empty=0
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
- policy: high->block (Claude exit2 / Codex stdout deny JSON+exit0);
  medium->warn->exit0; rule-specific suppression works; AG-BIDI not silenced unless
  allow_bidi_suppression set.
- hook exit codes: Claude pre-block=2, Claude post-block=2, allow=0, non-JSON=0,
  empty=0. Codex apply_patch pre-block=exit 0 WITH a stdout
  `permissionDecision:"deny"` JSON whose reason carries the block report; the real
  Codex payload shape (`tool_name:"apply_patch"`, `tool_input:{command}`,
  `hook_event_name` present) routes through the apply_patch parser and produces the
  added-line content (regression for the v0.3 misroute bug).
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

---

## 9. Codex hook wiring (real format) and verification

### 9.1 Config is TOML, not settings.json JSON

Codex hooks live in `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`) as
array-of-tables, modeled on Claude Code's three levels (event -> matcher group ->
handlers) but in TOML. The v0.3 hooks/codex.md showed a Claude-Code `settings.json`
JSON block, which Codex does NOT read. Correct form:

```toml
[[hooks.PreToolUse]]
matcher = "apply_patch"

[[hooks.PreToolUse.hooks]]
type = "command"
command = "agentgate hook --stdin"
```

`matcher` accepts a tool name (`apply_patch`, `Bash`) or a regex (`.*`). After
adding a hook, Codex requires you to trust it once (interactive), or pass
`--dangerously-bypass-hook-trust` for vetted automation.

### 9.2 Boundary-safe verification recipe (how 0.1 was measured)

To verify against a real Codex without touching the user's `~/.codex/config.toml`:

```
codex exec \
  --ignore-user-config \
  --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  --dangerously-bypass-hook-trust \
  -C <workdir> \
  -c 'hooks.PreToolUse=[{matcher="apply_patch",hooks=[{type="command",command="<hook>"}]}]' \
  "<task that triggers an apply_patch>"
```

Flags: `--ignore-user-config` skips the user's `config.toml`;
`--dangerously-bypass-hook-trust` runs the injected hook without persisted trust.
Auth still resolves from the default `CODEX_HOME`; `-c` injects the hook only for
that invocation; `config.toml` is never written. This is the exact harness used in
.codex-verify/ to capture the payload and block-mechanism evidence in 0.1.
