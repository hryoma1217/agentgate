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

### => Adapter routing requirement
The adapter must detect `apply_patch` first (via `tool_name == "apply_patch"` or a
`tool_input.command` that starts with `*** Begin Patch`) and route to the envelope
parser. A generic Claude-Code branch that only reads content/new_string/text would
return "" for the real Codex shape (which carries only `command`), making the gate
fail open. agentgate routes the real shape to the envelope parser.

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

### => Enforcement contract
For Codex, blocking requires emitting JSON permissionDecision=deny (or legacy
decision=block) on stdout with exit 0; exit 2 alone does NOT block apply_patch on
0.141.0 (it fails open). Config is TOML `[[hooks.PreToolUse]]` (array-of-tables),
not Claude-Code settings.json JSON.

## 4. Boundary-safe invocation recipe (for docs/automation)
- default CODEX_HOME (auth works)
- `--ignore-user-config` (don't read/depend on user's config.toml)
- inject hooks via `-c 'hooks.PreToolUse=[{matcher="apply_patch",hooks=[{type="command",command="..."}]}]'`
- `--dangerously-bypass-hook-trust` to skip the persisted-trust prompt for the run
- config.toml is never modified.

Real-world users instead persist the same table in ~/.codex/config.toml and run
`codex` trusting the hook once (no bypass flag needed).

## 5. End-to-end: the shipped agentgate blocks a real Codex apply_patch — CONFIRMED
Task: "create gadget.py whose only line is `x = \"<U+202E>danger\"`". The real Codex
payload (tool_name=apply_patch, tool_input.command = the bidi envelope) was fed to
the shipped `agentgate hook --stdin`. Result: stdout `permissionDecision:"deny"` +
exit 0; Codex logged `Command blocked by PreToolUse hook: agentgate: BLOCKED ... AG-BIDI`
and `hook: PreToolUse Blocked`; gadget.py was NEVER written. Reproduced 3/3
deterministically.

### Two Windows gotchas that cause silent fail-open
- **Hook command path must be Windows-style.** Codex is a native Windows exe; a hook
  `command` using an MSYS-style path (`/c/...`) cannot be spawned → Codex logs
  `hook: PreToolUse Failed` and fails OPEN. Use a Windows path (`C:/...`).
- **The hook must go through `main()` (i.e. `_enable_utf8_io`).** Calling `cmd_hook`
  directly bypasses the Windows UTF-8 stdin fix; stdin is then decoded as cp932, the
  payload's UTF-8 bidi bytes mojibake, the unicode check sees no control char, and the
  gate returns 0 (allow) → the write proceeds. The shipped `agentgate hook` entrypoint
  calls `main()` and is correct.
