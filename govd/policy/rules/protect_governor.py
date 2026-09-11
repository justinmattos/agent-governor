import json
import os
import re

from ...config import DEFAULT_PORT, GOVD_HOME, LAUNCH_AGENT_LABEL, LAUNCH_AGENT_PLIST, REPO_ROOT
from ..engine import ASK, BLOCK, Decision
from .base import Rule
from ._shell import _segments, _tokens

# Anything listed here changes what govd enforces or whether it runs at all.
# Touching it from inside a governed agent requires a human's approval (ASK), so
# a confused or prompt-injected agent cannot silently switch its governor off.
HOME = os.path.expanduser("~")
# This repo's own source. A session working inside the repo (cwd under
# REPO_ROOT) is the trusted case governor development happens in, so it edits
# these without a prompt; a session anywhere else still has to ask.
REPO_ROOTS = [
    os.path.realpath(os.path.join(REPO_ROOT, d))
    for d in ("adapters", "govd", "bin", "install")
]
# The running governor: its state, each agent's live hook config, the
# LaunchAgent. Changing any of these alters governance for every session, not
# just this repo's source, so it stays gated even from inside the repo.
LIVE_ROOTS = [
    os.path.realpath(p)
    for p in (
        GOVD_HOME,
        os.path.join(HOME, ".claude", "settings.json"),
        os.path.join(HOME, ".claude", "settings.local.json"),
        os.path.join(HOME, ".codex", "hooks.json"),
        os.path.join(HOME, ".cursor", "hooks.json"),
        LAUNCH_AGENT_PLIST,
    )
]
PROTECTED = REPO_ROOTS + LIVE_ROOTS
REPO_REAL = os.path.realpath(REPO_ROOT)

READ_ONLY = {
    "cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "rg", "ag", "ls",
    "wc", "diff", "stat", "file", "tree", "du", "bat", "md5", "shasum", "sha256sum",
    "cksum", "strings", "hexdump", "xxd", "od", "which", "type", "test", "[", "echo",
    "printf", "pwd", "true", "false", "sleep", "date", "jq", "sort", "uniq", "cut", "tr",
    "awk", "column", "nl", "tac", "rev", "basename", "dirname", "realpath", "readlink",
}
GIT_READ_ONLY = {
    "status", "log", "diff", "show", "blame", "ls-files", "rev-parse", "describe",
    "shortlog", "grep", "cat-file", "for-each-ref", "branch", "remote", "tag", "fetch",
}
MUTATORS = {
    "rm", "mv", "cp", "chmod", "chown", "ln", "truncate", "tee", "touch", "mkdir",
    "rmdir", "install", "rsync", "dd", "shred", "unlink", "patch",
}
KILL = {"kill", "pkill", "killall"}
GOVCTL_CONTROL = {"stop", "restart", "install-agent", "uninstall-agent", "hooks-sync"}
SETTINGS_FILES = {"settings.json", "settings.local.json"}

_WRITE_REDIRECT_OP = re.compile(r"^\d*>>?(&\d*)?$|^&>>?$")
_WRITE_REDIRECT_PREFIX = re.compile(r"^(\d*>>?|&>>?)")
_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete|Move to) File: (.+)$", re.M)
_DIFF_FILE = re.compile(r"^(?:\+\+\+|---) (?:[ab]/)?(\S+)", re.M)


def _display(path):
    return "~" + path[len(HOME):] if path.startswith(HOME + os.sep) else path


def _spellings(root):
    out = [root]
    if root.startswith(HOME + os.sep):
        rest = root[len(HOME):]
        out += ["~" + rest, "$HOME" + rest, "${HOME}" + rest]
    return out


def _spellings_for(roots):
    return [(root, s) for root in roots for s in _spellings(root)]


SPELLINGS = _spellings_for(PROTECTED)
SPELLINGS_LIVE = _spellings_for(LIVE_ROOTS)


def _session_in_repo(cwd):
    if not cwd:
        return False
    real = os.path.realpath(cwd)
    return real == REPO_REAL or real.startswith(REPO_REAL + os.sep)


def _protected_root(path, roots=PROTECTED):
    for root in roots:
        if path == root or path.startswith(root + os.sep):
            return root
    return None


def _resolve(tok, cwd):
    tok = _WRITE_REDIRECT_PREFIX.sub("", tok, count=1)
    if tok.startswith("-"):
        if "=" not in tok:
            return None
        tok = tok.split("=", 1)[1]
    if not tok:
        return None
    tok = tok.replace("${HOME}", HOME).replace("$HOME", HOME)
    tok = os.path.expanduser(tok)
    if not os.path.isabs(tok):
        if not cwd:
            return None
        tok = os.path.join(cwd, tok)
    return os.path.realpath(tok)


def _pathlike(tok):
    return "/" in tok or tok.startswith(("~", "$", "."))


def _is_read_only(prog, args):
    if prog in READ_ONLY:
        return True
    if prog == "sed":
        return not any(re.match(r"^-[A-Za-z]*i", a) or a.startswith("--in-place") for a in args)
    if prog == "find":
        return not any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls") for a in args)
    if prog == "git":
        sub = next((a for a in args if not a.startswith("-")), "")
        return sub in GIT_READ_ONLY
    return False


def _first_positional(args):
    return next((a for a in args if not a.startswith("-")), None)


def _check_shell(command, cwd, roots, spellings):
    if "disableAllHooks" in command:
        return "sets disableAllHooks, which turns every hook off"
    kill_seen = False
    cur = cwd
    for segment in _segments(command):
        toks = _tokens(segment)
        if not toks:
            continue
        prog = os.path.basename(toks[0])
        args = toks[1:]
        if prog in ("cd", "pushd"):
            target = _first_positional(args)
            cur = _resolve(target, cur) if target else HOME
            continue
        if prog == "govctl":
            sub = _first_positional(args) or ""
            if sub in GOVCTL_CONTROL:
                return f"runs `govctl {sub}`, which changes whether or how the governor runs or is wired into your agents"
            continue
        if prog in KILL:
            kill_seen = True
            continue
        if prog == "launchctl":
            if LAUNCH_AGENT_LABEL in segment or "govd" in segment:
                return "unloads or alters the govd LaunchAgent"
            continue
        read_only = _is_read_only(prog, args)
        prev = None
        for tok in toks:
            redirect_target = (prev is not None and _WRITE_REDIRECT_OP.match(prev)) or _WRITE_REDIRECT_PREFIX.match(tok)
            prev = tok
            if _WRITE_REDIRECT_OP.match(tok):
                continue
            if not redirect_target and (read_only or not (_pathlike(tok) or prog in MUTATORS)):
                continue
            path = _resolve(tok, cur)
            root = _protected_root(path, roots) if path else None
            if root:
                return f"writes to {_display(path)} (protected: {_display(root)})"
        if not read_only:
            for root, spelling in spellings:
                if spelling in segment:
                    return f"references {_display(root)} inside a `{prog}` invocation"
    if kill_seen:
        pid = str(os.getpid())
        if "govd" in command or re.search(rf"(?<!\d)({pid}|{DEFAULT_PORT})(?!\d)", command):
            return "kills the govd daemon process"
    return None


def _check_edit(data, cwd, roots):
    paths = [str(data[k]) for k in ("file_path", "notebook_path", "path", "file") if data.get(k)]
    patch = data.get("patch") or (data.get("input") if isinstance(data.get("input"), str) else "")
    if patch:
        paths += _PATCH_FILE.findall(patch) + _DIFF_FILE.findall(patch)
    for p in paths:
        resolved = _resolve(p, cwd)
        root = _protected_root(resolved, roots) if resolved else None
        if root:
            return f"edits {_display(resolved)} (protected: {_display(root)})"
    if any(os.path.basename(p) in SETTINGS_FILES for p in paths):
        pieces = [str(data.get(k) or "") for k in ("content", "new_string")]
        pieces += [str(e.get("new_string") or "") for e in (data.get("edits") or []) if isinstance(e, dict)]
        pieces.append(patch or "")
        if "disableAllHooks" in " ".join(pieces):
            return "sets disableAllHooks in a Claude Code settings file"
    return None


def _has_govd_hook(settings):
    for entries in (settings.get("hooks") or {}).values():
        for entry in entries if isinstance(entries, list) else []:
            for hook in (entry.get("hooks") or []) if isinstance(entry, dict) else []:
                if isinstance(hook, dict) and "adapters/claude_code.py" in (hook.get("command") or ""):
                    return True
    return False


def _check_config_change(data):
    source = data.get("source", "")
    path = data.get("file_path", "")
    if source not in ("user_settings", "project_settings", "local_settings") or not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            settings = json.load(fh)
    except Exception:
        return None
    if not isinstance(settings, dict):
        return None
    if settings.get("disableAllHooks") is True:
        return f"sets disableAllHooks in {_display(path)}"
    if source == "user_settings" and not _has_govd_hook(settings):
        return f"removes the govd hook from {_display(path)}"
    return None


class ProtectGovernor(Rule):
    name = "protect_governor"

    def applies(self, event):
        if event.event == "config_change":
            return True
        return event.event == "pre_tool_use" and event.tool in ("shell", "file_edit")

    def evaluate(self, event, ctx):
        data = event.input or {}
        if event.event == "config_change":
            what = _check_config_change(data)
            if not what:
                return None
            return Decision(
                decision=BLOCK,
                reason=f"govd: blocked a live settings change that {what}. Ask a human to apply it.",
                rule=self.name,
            )
        in_repo = _session_in_repo(event.cwd)
        roots = LIVE_ROOTS if in_repo else PROTECTED
        spellings = SPELLINGS_LIVE if in_repo else SPELLINGS
        if event.tool == "shell":
            what = _check_shell(data.get("command") or "", event.cwd, roots, spellings)
        else:
            what = _check_edit(data, event.cwd, roots)
        if not what:
            return None
        return Decision(
            decision=ASK,
            reason=(
                f"govd: this action {what}. Agents must not change or disable their own "
                "governance without a human's approval. Approve only if that is what you intend."
            ),
            rule=self.name,
        )
