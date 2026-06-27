#!/usr/bin/env python3
"""Verification hook: append stdin payload + argv + env-ish to a log, exit 0."""
import sys, os, json, datetime

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook_calls.log")

raw = sys.stdin.read()
rec = {
    "ts": datetime.datetime.now().isoformat(),
    "argv": sys.argv,
    "stdin_len": len(raw),
    "stdin_raw": raw,
}
try:
    rec["stdin_json"] = json.loads(raw)
except Exception as e:
    rec["stdin_json_error"] = str(e)

with open(LOG, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec, ensure_ascii=False) + "\n")

sys.exit(0)
