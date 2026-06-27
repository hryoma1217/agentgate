#!/usr/bin/env python3
"""Block-test hook: for apply_patch PreToolUse, emit a deny decision.

Mode is chosen by env AG_BLOCK_MODE:
  json  -> print hookSpecificOutput permissionDecision=deny, exit 0
  exit2 -> print reason to stderr, exit 2
  legacy-> print {"decision":"block","reason":...}, exit 0
"""
import sys, os, json, datetime

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "block_calls.log")
MODE = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AG_BLOCK_MODE", "json")

raw = sys.stdin.read()
try:
    payload = json.loads(raw)
except Exception:
    payload = {}

with open(LOG, "a", encoding="utf-8") as f:
    f.write(json.dumps({
        "ts": datetime.datetime.now().isoformat(),
        "mode": MODE,
        "event": payload.get("hook_event_name"),
        "tool": payload.get("tool_name"),
    }, ensure_ascii=False) + "\n")

is_pre = payload.get("hook_event_name") == "PreToolUse"
is_patch = payload.get("tool_name") == "apply_patch"

if is_pre and is_patch:
    reason = "agentgate BLOCK TEST: apply_patch denied by hook"
    if MODE in ("json", "json2"):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
        sys.stderr.write(reason + "\n")
        sys.exit(2 if MODE == "json2" else 0)
    elif MODE == "legacy":
        print(json.dumps({"decision": "block", "reason": reason}))
        sys.exit(0)
    else:  # exit2
        sys.stderr.write(reason + "\n")
        sys.exit(2)

sys.exit(0)
