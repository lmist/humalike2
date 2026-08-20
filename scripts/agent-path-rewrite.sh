#!/usr/bin/env bash
# PreToolUse hook for Codex (.codex/hooks.json) and Cursor (.cursor/hooks.json).
#
# Neither host lets a repo set PATH for the agent's shell, but both let a
# project hook rewrite the shell command before it runs. This reads the tool
# call JSON on stdin and, for shell commands, returns the same command with
# <repo>/bin first on PATH so `bd` is always the vendored build.
#
# Fail-open by design: anything unexpected → exit 0 with no output, and the
# host runs the original command unchanged.
#
# Usage: agent-path-rewrite.sh codex|cursor   (hook JSON on stdin)
set -u
HOST="${1:-codex}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export HOST ROOT
PYCODE=$(cat <<'PY'
import json, os, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
host, root = os.environ["HOST"], os.environ["ROOT"]
tool = d.get("tool_name") or ""
if host == "cursor" and tool != "Shell":
    sys.exit(0)
if host == "codex" and tool != "Bash":
    sys.exit(0)
ti = d.get("tool_input") or {}
cmd = ti.get("command")
prefix = 'export PATH="%s/bin:$PATH"; ' % root
if not isinstance(cmd, str) or cmd.startswith(prefix.rstrip()):
    sys.exit(0)
new = prefix + cmd
if host == "codex":
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "allow",
                                  "updatedInput": {"command": new}}}
else:
    ti = dict(ti)
    ti["command"] = new
    out = {"permission": "allow", "updated_input": ti}
print(json.dumps(out))
PY
)
exec python3 -c "$PYCODE"
