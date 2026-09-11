#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRE_TOOL = {"Shell": "shell", "Read": "file_read", "Write": "file_edit", "MCP": "mcp", "Task": "other"}
GOVD_HOME = os.path.expanduser(os.environ.get("GOVD_HOME", "~/.govd"))


def read_stdin():
    raw = sys.stdin.buffer.read()
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    return json.loads(raw.decode("utf-8") or "{}", strict=False)


def normalize(payload):
    name = payload.get("hook_event_name", "")
    if name == "beforeShellExecution":
        return "pre_tool_use", "shell", {"command": payload.get("command", ""), "cwd": payload.get("cwd", "")}
    if name == "beforeReadFile":
        return "pre_tool_use", "file_read", {"file_path": payload.get("file_path", ""), "content": payload.get("content", "")}
    if name == "beforeMCPExecution":
        return "pre_tool_use", "mcp", {"tool_name": payload.get("tool_name", ""), "tool_input": payload.get("tool_input", "")}
    if name == "beforeSubmitPrompt":
        return "user_prompt_submit", None, {"prompt": payload.get("prompt", "")}
    if name == "preToolUse":
        return "pre_tool_use", PRE_TOOL.get(payload.get("tool_name", ""), "other"), payload.get("tool_input") or {}
    if name == "afterShellExecution":
        return "post_tool_use", "shell", {"command": payload.get("command", "")}
    if name in ("afterFileEdit", "postToolUse"):
        return "post_tool_use", "file_edit", payload
    if name == "sessionEnd":
        return "session_end", None, {}
    if name == "sessionStart":
        return "session_start", None, {}
    if name == "stop":
        return "stop", None, {}
    return None, None, {}


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


def instructions():
    """Standing instructions for Cursor, rendered from the repo's `instructions/`.

    Cursor has no user-level rules file, so the adapter delivers them itself as
    `additional_context` from the `sessionStart` hook. Any failure logs and
    injects nothing — it must never break a session.
    """
    try:
        sys.path.insert(0, ROOT)
        from instrsync.sync import render
        return render("cursor")
    except Exception as exc:
        log_error(f"sessionStart: could not render instructions: {exc!r}")
        return ""


def log_error(message):
    try:
        os.makedirs(GOVD_HOME, mode=0o700, exist_ok=True)
        fd = os.open(os.path.join(GOVD_HOME, "adapter-errors.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} cursor {message}\n")
    except Exception:
        pass


def main():
    payload = read_stdin()
    event, tool, tool_input = normalize(payload)
    if not event:
        return 0

    norm = {
        "agent": "cursor",
        "event": event,
        "tool": tool,
        "raw_tool_name": payload.get("hook_event_name", ""),
        "input": tool_input,
        "cwd": payload.get("cwd") or (payload.get("workspace_roots") or [""])[0],
        "session_id": payload.get("conversation_id", ""),
    }
    if event == "session_start":
        context = instructions()
        try:
            ask(norm)  # audit only; the instructions do not depend on the daemon
        except Exception as exc:
            log_error(f"{event} {payload.get('hook_event_name', '')}: daemon unreachable: {exc!r}")
        if context:
            print(json.dumps({"additional_context": context}))
        return 0

    try:
        result = ask(norm)
    except Exception as exc:
        log_error(f"{event} {payload.get('hook_event_name', '')}: daemon unreachable: {exc!r}")
        return 0

    decision = result.get("decision", "allow")
    reason = result.get("reason", "")
    context = result.get("additional_context", "")

    if event == "pre_tool_use":
        if decision in ("deny", "block"):
            print(json.dumps({"permission": "deny", "agent_message": reason, "user_message": reason}))
        elif decision == "ask" and tool != "file_read":
            print(json.dumps({"permission": "ask", "user_message": reason}))
        else:
            # Cursor has no abstain: empty output is fail-open, same as allow.
            print(json.dumps({"permission": "allow"}))
    elif event == "user_prompt_submit":
        if decision in ("deny", "block"):
            print(json.dumps({"continue": False, "user_message": reason}))
        else:
            print(json.dumps({"continue": True}))
    elif event == "post_tool_use":
        if context:
            print(json.dumps({"additional_context": context, "user_message": context}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log_error(f"adapter crashed: {exc!r}")
        sys.exit(0)
