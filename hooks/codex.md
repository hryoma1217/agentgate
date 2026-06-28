# agentgate hooks for Codex

Wire agentgate into Codex CLI's hook system for the `apply_patch` tool.

Verified against codex-cli 0.141.0. The block contract below (stdout JSON
`permissionDecision: "deny"` + exit 0) and the firing facts were measured
empirically; see `docs/codex-verification.md` in this repo for the raw evidence.

## Supported tool: apply_patch only

Codex wraps file writes in `apply_patch` envelopes:

```
*** Begin Patch
*** Add File: path/to/file.py
+added line one
+added line two
*** End Patch
```

agentgate's adapter parses this envelope to extract the added (`+`-prefixed)
lines and target path. Only `apply_patch` is supported. Other Codex tool paths
(shell commands, codegen scripts, etc.) are not hooked and fail-open (gate does
nothing).

The real Codex payload carries BOTH `hook_event_name` AND
`tool_name: "apply_patch"` AND `tool_input.command` (the envelope). agentgate
detects `apply_patch` first, so this real shape is routed to the envelope parser
rather than the generic Claude-Code branch.

## Config is TOML (not settings.json)

Codex hooks live in `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`) as
array-of-tables. The three levels mirror Claude Code (event -> matcher group ->
handlers) but the file format is TOML, not JSON.

### PreToolUse (block before the write)

```toml
[[hooks.PreToolUse]]
matcher = "apply_patch"

[[hooks.PreToolUse.hooks]]
type = "command"
command = "agentgate hook --stdin"
```

`matcher` accepts a tool name (`apply_patch`, `Bash`) or a regex (`.*`). After
adding a hook, Codex requires you to trust it once interactively, or pass
`--dangerously-bypass-hook-trust` for vetted automation.

### PostToolUse (logging only)

```toml
[[hooks.PostToolUse]]
matcher = "apply_patch"

[[hooks.PostToolUse.hooks]]
type = "command"
command = "agentgate hook --stdin"
```

apply_patch fires PostToolUse as well, but it runs **after** the write is already
applied. PostToolUse cannot prevent or undo the write — agentgate uses it for
logging only (block report to stderr; no deny JSON is emitted). Use PreToolUse if
you want enforcement.

## Enforcement contract (Codex differs from Claude Code)

On a blocking finding for a Codex `apply_patch` PreToolUse, agentgate emits the
deny decision on **stdout as JSON** and exits **0**:

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"<agentgate block report>"}}
```

This rejects the patch; the model sees the reason and can rewrite. agentgate also
writes the block report to stderr for the human.

**Important — exit code 2 fails OPEN on Codex.** Unlike Claude Code (where exit 2
+ stderr blocks), Codex treats a hook exit code of 2 as a hook failure, logs
`hook: PreToolUse Failed`, and lets the write proceed. agentgate therefore uses
the stdout-JSON-deny + exit-0 path for Codex and reserves exit 2 for Claude Code.
This is why the gate is agent-aware: it detects `agent == "codex"` from the
payload and switches the block mechanism accordingly.

Exit code 0 with empty stdout allows the patch to proceed.

## Coverage limits

agentgate only sees content from `apply_patch` envelopes. It does NOT see:

- Files written by shell commands the agent runs (`echo >`, `sed -i`, etc.)
- Pre-existing file content (only the `+`-prefixed added lines are checked)
- Codex tool calls other than `apply_patch`

Additional M1 limitations:

- **Multi-file apply_patch:** when one envelope touches several files, the block
  report attributes findings to the first file path in the envelope. The added
  lines from all hunks are still scanned; only the displayed path is the first.
- If the `apply_patch` envelope cannot be parsed, agentgate exits 0 (fail-open).
  The gate must never block an agent on malformed input.

## Boundary-safe verification (no config.toml writes)

To verify against a real Codex without touching `~/.codex/config.toml`, inject the
hook ephemerally with `-c`:

```
codex exec \
  --ignore-user-config \
  --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  --dangerously-bypass-hook-trust \
  -C <workdir> \
  -c 'hooks.PreToolUse=[{matcher="apply_patch",hooks=[{type="command",command="agentgate hook --stdin"}]}]' \
  "<task that triggers an apply_patch>"
```

Flags: `--ignore-user-config` skips the user's `config.toml`;
`--dangerously-bypass-hook-trust` runs the injected hook without persisted trust.
Auth still resolves from the default `CODEX_HOME`; `-c` injects the hook only for
that one invocation; `config.toml` is never written.

## Notes

- Codex may supply `tool_input.command` as a string or as an argv list;
  agentgate handles both.
- Non-JSON or empty stdin always exits 0 (fail-open).
