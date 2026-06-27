# Codex hooks empirical verification (codex-cli 0.141.0, Windows)

Ran real `codex exec` with hooks injected ephemerally via `-c` (config.toml never
written). Auth via default CODEX_HOME; `--ignore-user-config` so the user's
config.toml is not loaded. `--dangerously-bypass-hook-trust` to run injected hooks.

## 1. Hooks fire for apply_patch — CONFIRMED
A trivial "create greeting.txt" task fired:
- PreToolUse  tool_name=apply_patch  (twice: once per matching matcher "apply_patch" and ".*")
- PostToolUse tool_name=apply_patch
- PreToolUse/PostToolUse tool_name=Bash (for the powershell verify step)

So apply_patch DOES emit PreToolUse + PostToolUse. (Earlier third-party claim that
apply_patch PreToolUse may not fire is FALSE for 0.141.0.)

## 2. Real stdin payload shape — CONFIRMED
apply_patch PreToolUse JSON keys:
```
session_id, turn_id, transcript_path, cwd, hook_event_name, model,
permission_mode, tool_name, tool_input, tool_use_id
```
PostToolUse adds: tool_response.
Values observed:
- hook_event_name = "PreToolUse" / "PostToolUse"
- tool_name       = "apply_patch"   (canonical; NOT "Write"/"Edit")
- tool_input      = {"command": "<full apply_patch envelope>"}
- permission_mode = "bypassPermissions"
- tool_use_id     = "exec-<uuid>"
- cwd             = absolute workdir

tool_input.command holds the raw envelope:
```
*** Begin Patch
*** Add File: greeting.txt
+hello from codex
*** End Patch
```

### => Adapter bug confirmed
agentgate `adapter.from_stdin_json` branch 1 fires on (hook_event_name AND tool_name),
routes to claude-code `_extract_content(tool_input)` which only looks for
content/new_string/text. Real Codex tool_input has only `command` => returns "" =>
gate sees no text => exit 0 => apply_patch corruption MISSED (fail-open). The Codex
branch (checks tool_input.command for "*** Begin Patch") is never reached because
branch 1 already matched. Existing tests used a synthetic shape lacking
hook_event_name/tool_name = false-green.

## 3. Block mechanism — CONFIRMED which ones actually prevent the write
Same "create blocked.txt" task, apply_patch matcher, three hook return styles:

| Mechanism                                                   | Result        |
|-------------------------------------------------------------|---------------|
| JSON {"hookSpecificOutput":{...,"permissionDecision":"deny","permissionDecisionReason":...}}, exit 0 | BLOCKS (file NOT written) |
| legacy JSON {"decision":"block","reason":...}, exit 0        | BLOCKS (file NOT written) |
| exit code 2 + stderr                                        | DOES NOT BLOCK — logs "hook: PreToolUse Failed", apply_patch completes, file IS written (fail-open) |

On a real block Codex logs:
`ERROR codex_core::tools::router: error=Command blocked by PreToolUse hook: <reason>`
prints `hook: PreToolUse Blocked`, and surfaces the reason to the model, which then
self-corrects (did not retry via shell when instructed).

### => README/hooks doc bug confirmed
agentgate README and hooks/codex.md claim "hook: exit 2 = block" and show a
Claude-Code JSON settings.json config. For Codex BOTH are wrong:
- Config is TOML `[[hooks.PreToolUse]]` (array-of-tables), not settings.json JSON.
- Blocking requires emitting JSON permissionDecision=deny (or legacy decision=block);
  exit 2 alone does NOT block apply_patch on 0.141.0.

## 4. Boundary-safe invocation recipe (for docs/automation)
- default CODEX_HOME (auth works)
- `--ignore-user-config` (don't read/depend on user's config.toml)
- inject hooks via `-c 'hooks.PreToolUse=[{matcher="apply_patch",hooks=[{type="command",command="..."}]}]'`
- `--dangerously-bypass-hook-trust` to skip the persisted-trust prompt for the run
- config.toml is never modified.

Real-world users instead persist the same table in ~/.codex/config.toml and run
`codex` trusting the hook once (no bypass flag needed).

## 5. End-to-end: the SHIPPED agentgate blocks a real Codex apply_patch — CONFIRMED
Task: "create gadget.py whose only line is `x = \"<U+202E>danger\"`". The real Codex
payload (tool_name=apply_patch, tool_input.command = the bidi envelope) was fed to
the shipped `agentgate hook --stdin`. Result: stdout `permissionDecision:"deny"` +
exit 0; Codex logged `Command blocked by PreToolUse hook: agentgate: BLOCKED ... AG-BIDI`
and `hook: PreToolUse Blocked`; gadget.py was NEVER written. Reproduced 3/3
deterministically. (`run_real_block.sh` + `real_gate.py`.)

### Two Windows gotchas that cause silent fail-open (both bit the harness, not the product)
- **Hook command path must be Windows-style.** Codex is a native Windows exe; a hook
  `command` using an MSYS path (`/d/work/.../hook.py`) cannot be spawned → Codex logs
  `hook: PreToolUse Failed` and fails OPEN. Use `D:/work/.../hook.py`. (Explains every
  earlier "Failed": the harness used `/d/...`; `run_block.sh` used `D:/...` and blocked.)
- **The hook must go through `main()` (i.e. `_enable_utf8_io`).** Calling `cmd_hook`
  directly bypasses the Windows UTF-8 stdin fix; stdin is then decoded as cp932, the
  payload's UTF-8 bidi bytes mojibake, the unicode check sees no control char, and the
  gate returns 0 (allow) → Codex logs `hook: PreToolUse Completed` and the write
  proceeds. The shipped `agentgate hook` entrypoint calls `main()` and is correct; only
  the test wrapper had to be fixed to call `cli.main(["hook","--stdin"])`.
