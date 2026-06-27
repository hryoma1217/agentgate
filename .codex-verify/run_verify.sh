#!/usr/bin/env bash
# Empirical Codex hooks verification. Uses default CODEX_HOME for auth,
# --ignore-user-config so the user's ~/.codex/config.toml is NOT loaded,
# and injects hooks ephemerally via -c. config.toml is never written.
set -u

CODEX=/c/Users/ettex/AppData/Local/Volta/bin/codex
PY="C:/Users/ettex/AppData/Local/Programs/Python/Python310/python.exe"
HOOK="$PY D:/work/dev/claude/agentgate/.codex-verify/log_hook.py"
DIR=/d/work/dev/claude/agentgate/.codex-verify
WORK="$DIR/work"

rm -f "$DIR/hook_calls.log"
rm -rf "$WORK"; mkdir -p "$WORK"

PRE="hooks.PreToolUse=[{matcher=\"apply_patch\",hooks=[{type=\"command\",command=\"$HOOK\"}]},{matcher=\".*\",hooks=[{type=\"command\",command=\"$HOOK\"}]},{matcher=\"Bash\",hooks=[{type=\"command\",command=\"$HOOK\"}]}]"
POST="hooks.PostToolUse=[{matcher=\".*\",hooks=[{type=\"command\",command=\"$HOOK\"}]}]"

echo "=== invoking codex exec ==="
"$CODEX" exec \
  --ignore-user-config \
  --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  --dangerously-bypass-hook-trust \
  -C "$WORK" \
  -c "$PRE" \
  -c "$POST" \
  "Create a new file named greeting.txt containing exactly the line: hello from codex" \
  < /dev/null 2>&1

echo "=== exit code: $? ==="
echo "=== work dir ==="
ls -la "$WORK"
echo "=== hook_calls.log present? ==="
ls -la "$DIR/hook_calls.log" 2>&1
