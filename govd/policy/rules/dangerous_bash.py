import os
import re

from ..engine import DENY, Decision
from .base import Rule
from ._shell import _segments, _tokens

HOME = os.path.realpath(os.path.expanduser("~"))

# Recursively deleting or re-permissioning any of these takes the machine, or
# the user's whole account, down with it. Deeper paths are fair game.
SYSTEM_DIRS = {
    "/", "/System", "/System/Library", "/Library", "/Applications", "/Users",
    "/private", "/private/var", "/private/etc", "/usr", "/usr/bin", "/usr/sbin",
    "/usr/lib", "/usr/local", "/etc", "/var", "/var/db", "/bin", "/sbin", "/opt",
    "/dev", "/proc", "/sys", "/boot", "/lib", "/lib64", "/home", "/root", "/srv",
}
CWD_ALIASES = {".", "./", "*", "./*", ".*", "./.*"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
WRAPPERS = {"exec", "time", "nice", "ionice", "builtin", "caffeinate", "timeout", "doas", "xargs"}
VALUE_FLAGS = {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-T", "-U", "-n", "-I", "-P", "-L", "-s", "-E", "-d", "-c", "-w"}
SSH_VALUE_FLAGS = {"-p", "-i", "-l", "-o", "-J", "-F", "-L", "-R", "-D", "-W", "-E", "-b", "-c", "-m", "-O", "-Q", "-S", "-w", "-B", "-I"}
DELETERS = {"rm", "shred", "unlink", "rmdir"}

_DEV = r"/dev/(?:r?disk|sd|nvme|hd|mmcblk|xvd|vd)[a-z0-9]*\b"
CATASTROPHIC_TEXT = [
    (re.compile(r"([A-Za-z_:][\w:]*)\s*\(\s*\)\s*\{[^}]*\1\s*\|\s*\1\s*&"), "fork bomb"),
    (re.compile(r"\bmkfs(?:\.[a-z0-9]+)?\b"), "filesystem format"),
    (re.compile(r"\bwipefs\b"), "filesystem signature wipe"),
    (re.compile(r"\bdiskutil\s+(?:eraseDisk|eraseVolume|zeroDisk|secureErase|randomDisk|partitionDisk|reformat)\b"), "disk erase"),
    (re.compile(r"\bdd\b[^|;&\n]*\bof=" + _DEV), "raw write to a block device"),
    (re.compile(r">\s*" + _DEV), "redirect over a block device"),
    (re.compile(r"\bshred\b[^|;&\n]*\s" + _DEV), "shred of a block device"),
]


def _expand(tok):
    tok = tok.replace("${HOME}", HOME).replace("$HOME", HOME)
    return os.path.expanduser(tok)


def _wipe_root(tok, cwd):
    path = _expand(tok)
    if path in CWD_ALIASES:
        if not cwd:
            return None
        path = cwd
    if not path.startswith("/"):
        return None
    core = os.path.normpath(path.rstrip("/*.") or "/")
    if core in SYSTEM_DIRS:
        return core
    if core == HOME or os.path.realpath(core) == HOME:
        return "~"
    return None


def _rm_args(args):
    recursive = False
    targets = []
    literal = False
    for a in args:
        if literal:
            targets.append(a)
        elif a == "--":
            literal = True
        elif a.startswith("--"):
            recursive = recursive or a == "--recursive"
        elif a.startswith("-") and len(a) > 1:
            recursive = recursive or any(c in "rR" for c in a[1:])
        else:
            targets.append(a)
    return recursive, targets


def _recursive_flag(args):
    return any(
        a in ("-R", "--recursive") or (a.startswith("-") and not a.startswith("--") and "R" in a[1:])
        for a in args
    )


def _dash_c_script(args):
    for i, a in enumerate(args):
        if a.startswith("-") and not a.startswith("--") and "c" in a[1:] and i + 1 < len(args):
            return args[i + 1]
    return None


def _ssh_remote_command(args):
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in SSH_VALUE_FLAGS else 1
    return " ".join(args[i + 1:])


def _strip_wrappers(toks):
    while toks:
        head = os.path.basename(toks[0])
        if head.startswith("-") and len(head) > 1:
            toks = toks[2:] if head in VALUE_FLAGS else toks[1:]
        elif head in WRAPPERS:
            toks = toks[1:]
            if head == "timeout":
                while toks and toks[0].startswith("-"):
                    toks = toks[1:]
                toks = toks[1:]
        elif re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head):
            toks = toks[1:]
        else:
            break
    return toks


def _classify(prog, args, cwd):
    if prog == "rm":
        recursive, targets = _rm_args(args)
        if recursive:
            for t in targets:
                root = _wipe_root(t, cwd)
                if root:
                    return f"recursive delete of {root}"
    elif prog in ("chmod", "chown", "chgrp"):
        if _recursive_flag(args):
            positionals = [a for a in args if not a.startswith("-")]
            for t in positionals[1:]:
                root = _wipe_root(t, cwd)
                if root:
                    return f"recursive permission change on {root}"
    elif prog == "find":
        starts = []
        for a in args:
            if a.startswith("-") or a in ("(", "!"):
                break
            starts.append(a)
        deletes = "-delete" in args or any(
            a in ("-exec", "-execdir", "-ok", "-okdir") and i + 1 < len(args)
            and os.path.basename(args[i + 1]) in DELETERS
            for i, a in enumerate(args)
        )
        if deletes:
            for s in starts or ["."]:
                root = _wipe_root(s, cwd)
                if root:
                    return f"recursive delete under {root}"
    return None


def _scan(command, cwd, depth=0):
    for segment in _segments(command):
        toks = _strip_wrappers(_tokens(segment))
        if not toks:
            continue
        prog = os.path.basename(toks[0])
        args = toks[1:]
        label = None
        if depth < 3 and prog in SHELLS:
            script = _dash_c_script(args)
            label = _scan(script, cwd, depth + 1) if script else None
        elif depth < 3 and prog == "eval":
            label = _scan(" ".join(args), cwd, depth + 1)
        elif depth < 3 and prog == "ssh":
            remote = _ssh_remote_command(args)
            label = _scan(remote, "", depth + 1) if remote else None
        else:
            label = _classify(prog, args, cwd)
        if label:
            return label
    return None


class DangerousBash(Rule):
    name = "dangerous_bash"

    def applies(self, event):
        return event.event == "pre_tool_use" and event.tool == "shell"

    def evaluate(self, event, ctx):
        command = (event.input or {}).get("command") or ""
        if not command.strip():
            return None
        label = None
        for pattern, text_label in CATASTROPHIC_TEXT:
            if pattern.search(command):
                label = text_label
                break
        if label is None:
            label = _scan(command, event.cwd or "")
        if label is None:
            return None
        return Decision(
            decision=DENY,
            reason=f"Blocked by govd: command matches a catastrophic pattern ({label}).",
            rule=self.name,
        )
