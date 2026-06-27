#!/usr/bin/env bash
# Test which PreToolUse block mechanism actually prevents an apply_patch write.
# Usage: bash run_block.sh <json|exit2|legacy>
set -u
MODE="${1:-json}"
export AG_BLOCK_MODE="$MODE"

CODEX=/c/Users/ettex/AppData/Local/Volta/bin/codex
PY="C:/Users/ettex/AppData/Local/Programs/Python/Python310/python.exe"
HOOK="$PY D:/work/dev/claude/agentgate/.codex-verify/block_hook.py $MODE"
DIR=/d/work/dev/claude/agentgate/.codex-verify
WORK="$DIR/work_block"

rm -f "$DIR/block_calls.log"
rm -rf "$WORK"; mkdir -p "$WORK"

PRE="hooks.PreToolUse=[{matcher=\"apply_patch\",hooks=[{type=\"command\",command=\"$HOOK\"}]}]"

echo "=== MODE=$MODE :: invoking codex exec ==="
AG_BLOCK_MODE="$MODE" "$CODEX" exec \
  --ignore-user-config \
  --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  --dangerously-bypass-hook-trust \
  -C "$WORK" \
  -c "$PRE" \
  "Create a new file named blocked.txt containing exactly: should not exist. Do not retry with shell if apply_patch is denied." \
  < /dev/null 2>&1

echo "=== exit code: $? ==="
echo "=== did blocked.txt get written? ==="
ls -la "$WORK"
echo "=== block_calls.log ==="
cat "$DIR/block_calls.log" 2>&1
