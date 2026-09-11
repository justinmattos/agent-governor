#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.request

EVENT_MAP = {
    "PreToolUse": "pre_tool_use",
    "PostToolUse": "post_tool_use",
    "UserPromptSubmit": "user_prompt_submit",
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    "Stop": "stop",
    "ConfigChange": "config_change",
}
GOVD_HOME = os.path.expanduser(os.environ.get("GOVD_HOME", "~/.govd"))
UNREACHABLE = (
    "govd is unreachable, so this action ran ungoverned (fail-open). "
    "Run `bin/govctl status`; details in ~/.govd/adapter-errors.log."
)


def tool_of(name):
    if name == "Bash":
        return "shell"
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "file_edit"
    if name == "Read":
        return "file_read"
    if name == "ExitPlanMode":
        return "plan"
    if name.startswith("mcp__"):
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
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} claude_code {message}\n")
    except Exception:
        pass


def emit_pre(decision, reason):
    # No output on allow: an explicit "allow" would skip Claude Code's own
    # permission prompt, and govd only adds gates, never removes them.
    if decision == "allow":
        return
    pd = "deny" if decision in ("deny", "block") else "ask"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": pd,
            "permissionDecisionReason": reason,
        }
    }))


def main():
    payload = json.loads(sys.stdin.read() or "{}", strict=False)
    event = EVENT_MAP.get(payload.get("hook_event_name", ""))
    if not event:
        return 0

    tool_name = payload.get("tool_name", "")
    norm = {
        "agent": "claude_code",
        "event": event,
        "tool": tool_of(tool_name) if tool_name else None,
        "raw_tool_name": tool_name,
        "input": payload.get("tool_input") or {},
        "cwd": payload.get("cwd", ""),
        "session_id": payload.get("session_id", ""),
    }
    if event == "user_prompt_submit":
        norm["input"] = {"prompt": payload.get("prompt", "")}
    elif event == "config_change":
        norm["input"] = {"source": payload.get("source", ""), "file_path": payload.get("file_path", "")}

    try:
        result = ask(norm)
    except Exception as exc:
        log_error(f"{event} {tool_name or '-'}: daemon unreachable: {exc!r}")
        if event == "pre_tool_use":
            print(json.dumps({"systemMessage": UNREACHABLE}))
        return 0

    decision = result.get("decision", "allow")
    reason = result.get("reason", "")
    context = result.get("additional_context", "")

    if event == "pre_tool_use":
        emit_pre(decision, reason)
    elif event == "post_tool_use":
        if decision == "block":
            sys.stderr.write(reason or context)
            return 2
        if context:
            print(json.dumps({
                "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}
            }))
    elif event == "user_prompt_submit":
        if decision in ("deny", "block"):
            sys.stderr.write(reason)
            return 2
        if context:
            print(context)
    elif event == "config_change":
        if decision in ("deny", "block"):
            # Claude Code shows nothing for a blocked ConfigChange, so keep a record.
            log_error(f"ConfigChange blocked ({payload.get('file_path', '')}): {reason}")
            print(json.dumps({"decision": "block", "reason": reason}))
    elif event == "stop":
        if decision in ("deny", "block"):
            # Keep Claude in the turn until the reason is addressed (e.g. a plan
            # under .context/plans/ that doesn't meet the format). Claude Code caps
            # consecutive Stop blocks, so this can't loop forever.
            print(json.dumps({"decision": "block", "reason": reason or context}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log_error(f"adapter crashed: {exc!r}")
        sys.exit(0)
