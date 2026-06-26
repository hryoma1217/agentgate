# agentgate hooks for Codex

Wire agentgate into Codex's hook system for the `apply_patch` tool.

## Supported tool: apply_patch only

Codex wraps file writes in `apply_patch` envelopes:

```
*** Begin Patch
*** Add File: path/to/file.py
+added line one
+added line two
*** End Patch
```

agentgate's adapter parses this envelope to extract the added lines and target
path. Only `apply_patch` is supported. Other Codex tool paths (shell commands,
codegen scripts, etc.) are not hooked and fail-open (gate does nothing).

## PreToolUse setup

Configure in your Codex hook config:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "apply_patch",
        "hooks": [
          {
            "type": "command",
            "command": "agentgate hook --stdin"
          }
        ]
      }
    ]
  }
}
```

**Enforcement:** Exit code 2 rejects the `apply_patch` call. The write does not
happen. The model sees stderr (the agentgate block report) and can rewrite.

Exit code 0 allows the patch to proceed.

## PostToolUse setup

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "apply_patch",
        "hooks": [
          {
            "type": "command",
            "command": "agentgate hook --stdin"
          }
        ]
      }
    ]
  }
}
```

PostToolUse runs after the patch is applied. Exit code 2 feeds remediation text
back to the model; it does **not** undo the already-applied patch.

## Coverage limits

agentgate only sees content from `apply_patch` envelopes. It does NOT see:

- Files written by shell commands the agent runs (`echo >`, `sed -i`, etc.)
- Pre-existing file content (only the `+`-prefixed added lines are checked)
- Codex tool calls other than `apply_patch`

If the `apply_patch` envelope cannot be parsed, agentgate exits 0 (fail-open).
The gate must never block an agent on malformed input.

## Notes

- Codex may supply `tool_input.command` as a string or as an argv list;
  agentgate handles both.
- Non-JSON or empty stdin always exits 0 (fail-open).
