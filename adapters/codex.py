#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.request

EVENT_MAP = {
    "PreToolUse": "pre_tool_use",
    "PermissionRequest": "pre_tool_use",
    "PostToolUse": "post_tool_use",
    "UserPromptSubmit": "user_prompt_submit",
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    "Stop": "stop",
}
GOVD_HOME = os.path.expanduser(os.environ.get("GOVD_HOME", "~/.govd"))
CANNOT_ASK = " (govd cannot prompt on Codex, so this 'ask' is enforced as a deny.)"


def tool_of(name):
    if name == "Bash":
        return "shell"
    if name == "apply_patch":
        return "file_edit"
    if name.startswith("mcp"):
        return "mcp"
    return "other"


def port():
    env = os.environ.get("GOVD_PORT")
    if env:
        return int(env)
    try:
        with open(os.path.join(GOVD_HOME, "port")) as fh:
            return int(fh.read().strip())
    except Exception:
        return 8787


def ask(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port()}/v1/evaluate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=2.0) as resp:
        return json.loads(resp.read())


def log_error(message):
    try:
        os.makedirs(GOVD_HOME, mode=0o700, exist_ok=True)
        fd = os.open(os.path.join(GOVD_HOME, "adapter-errors.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} codex {message}\n")
    except Exception:
        pass


def main():
    payload = json.loads(sys.stdin.read() or "{}", strict=False)
    hook_name = payload.get("hook_event_name", "")
    event = EVENT_MAP.get(hook_name)
    if not event:
        return 0

    tool_name = payload.get("tool_name", "")
    norm = {
        "agent": "codex",
        "event": event,
        "tool": tool_of(tool_name) if tool_name else None,
        "raw_tool_name": tool_name,
        "input": payload.get("tool_input") or {},
        "cwd": payload.get("cwd", ""),
        "session_id": payload.get("session_id", ""),
    }
    try:
        result = ask(norm)
    except Exception as exc:
        log_error(f"{event} {tool_name or '-'}: daemon unreachable: {exc!r}")
        return 0

    decision = result.get("decision", "allow")
    reason = result.get("reason", "")
    context = result.get("additional_context", "")

    # Codex honors deny but has no "ask"; an unanswerable ask must fail closed.
    denied = decision in ("deny", "block", "ask")
    if decision == "ask":
        reason += CANNOT_ASK

    if hook_name == "PermissionRequest":
        if denied:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "deny", "message": reason},
                }
            }))
        return 0

    if hook_name == "PreToolUse":
        if denied:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }))
        return 0

    if event == "post_tool_use" and decision == "block":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "decision": "block",
                "reason": reason or context,
            }
        }))

    if hook_name == "Stop" and denied:
        # Codex Stop takes a top-level decision, and the reason is injected as the
        # next user message — so an unmet plan_format keeps the turn going.
        print(json.dumps({"decision": "block", "reason": reason or context}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log_error(f"adapter crashed: {exc!r}")
        sys.exit(0)
