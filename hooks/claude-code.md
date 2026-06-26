# agentgate hooks for Claude Code

Wire agentgate into Claude Code using its PreToolUse and PostToolUse hook system.

## PreToolUse (true prevention)

Add to your `.claude/settings.json` or `settings.local.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
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

**Enforcement:** When `agentgate hook --stdin` exits with code 2, Claude Code
**denies** the tool call entirely -- the write never happens. The stderr output
is shown to the model so it can self-correct and re-issue a fixed write.

Exit code 0 means allow; the write proceeds normally.

## PostToolUse (feedback / remediation)

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
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

**Important:** PostToolUse runs *after* the file has been written. Exit code 2
here surfaces the agentgate report to the model as feedback so it can issue a
corrective follow-up write. It does **not** roll back the write that already
happened. Only PreToolUse provides true prevention.

## Choosing Pre vs Post

| Mode        | Prevents write? | Effect of exit 2                     |
|-------------|-----------------|--------------------------------------|
| PreToolUse  | Yes             | Denies the call; model sees stderr   |
| PostToolUse | No              | Write done; model sees remediation   |

For security-critical rules (AG-BIDI bidi controls, AG-INVIS invisible chars),
use PreToolUse so the write is blocked before it lands on disk.

## Notes

- agentgate reads config from `agentgate.toml` or `[tool.agentgate]` in
  `pyproject.toml` in the current working directory.
- Default config has `cjk = false` (requires `pip install agentgate[cjk]` to enable).
- Non-JSON or empty input always exits 0 (fail-open; gate never wedges the agent).
