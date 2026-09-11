import re
import shlex
import subprocess
from datetime import datetime, timezone

from ..engine import ALLOW, DENY, Decision
from .base import Rule

RESOURCE = "typecheck"
# pgrep covers the running tsc; the lock only closes the startup race before the
# process is visible, so a short TTL bounds a crashed session's stale hold.
TTL_SECONDS = 45

# Package-manager / task runners whose non-flag argument names the script or
# binary they execute. A type-check token in that position means the command
# really launches tsc — directly, or via a workspace script (`pnpm typecheck`,
# `pnpm -r typecheck`, `pnpm --dir web typecheck`), which the old bare-`tsc`
# match missed entirely.
_RUNNERS = frozenset((
    "pnpm", "pnpx", "yarn", "npm", "npx", "bun", "bunx", "node", "deno",
    "make", "turbo", "nx", "just", "lerna", "wireit",
))
# Wrappers that prefix the real command; skip them to find the executable.
_PREFIX_WRAPPERS = frozenset((
    "sudo", "env", "command", "nice", "nohup", "time", "exec", "xargs",
))

# Script/binary names that mean "type-check" in command position: the tsc/tsgo
# binaries and the conventional wrapper script names (typecheck, type-check,
# tsc:inc, typecheck:workspaces, ...).
_INVOKE_TOKEN = re.compile(r"(?i)^(tsc|tsgo|type-?check)(:[0-9A-Za-z._-]+)?$")
# A *running* type-check process resolves to the tsc/tsgo binary (optionally its
# .js/.mjs entrypoint) as the executable — never a wrapper script name.
_RUN_TOKEN = re.compile(r"(?i)^(tsc|tsgo)(\.[cm]?js)?$")

_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_EVAL_FLAGS = frozenset(("-e", "--eval", "-p", "--print"))
_OPERATOR = re.compile(r"^[;|&()<>{}\n]+$|^\d*[<>]&?\d*$")
_FALLBACK_SPLIT = re.compile(r"[\n;|&()<>{}]+")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def _strip_heredocs(command):
    # A heredoc feeds literal data to a program's stdin; its lines are not shell
    # commands, so a `typecheck` mentioned in README text being rewritten by a
    # `python3 - <<'EOF'` block must not read as a type-check invocation.
    for _ in range(20):
        m = _HEREDOC.search(command)
        if not m:
            break
        delim = m.group(2)
        nl = command.find("\n", m.end())
        if nl == -1:
            command = command[:m.start()] + " " + command[m.end():]
            continue
        close = re.compile(r"^[ \t]*" + re.escape(delim) + r"[ \t]*$", re.M)
        cm = close.search(command, nl + 1)
        if not cm:
            command = command[:m.start()] + " " + command[m.end():nl]
            break
        command = command[:m.start()] + " " + command[m.end():nl] + command[cm.end():]
    return command


def _basename(word):
    w = word.strip().strip("'\"(){}")
    if "/" in w:
        w = w.rsplit("/", 1)[-1]
    return w


def _segments(command):
    # Split into simple commands, each a list of word tokens. A quote-aware lexer
    # keeps operators, parens, and newlines that appear inside quotes (grep
    # '...\|...', node -e 'a\ntsc=1') attached to their token, while unquoted
    # separators split one simple command from the next — so a token only counts
    # when it is actually in command position, not merely mentioned.
    command = _strip_heredocs(command.replace("\r\n", "\n").replace("\r", "\n"))
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
        lex.whitespace_split = True
        lex.whitespace = lex.whitespace.replace("\n", "")
        tokens = list(lex)
    except ValueError:
        # Unbalanced quotes (complex inline scripts): fall back to a naive split.
        # It over-matches rather than under-matches, the safe direction for a
        # guard whose job is to catch launches.
        return [seg.split() for seg in _FALLBACK_SPLIT.split(command)]
    segments, cur = [], []
    for tok in tokens:
        if _OPERATOR.match(tok):
            segments.append(cur)
            cur = []
        else:
            cur.append(tok)
    segments.append(cur)
    return segments


def _is_noise(word):
    return (">" in word) or ("<" in word) or bool(_ASSIGN.match(word))


def _executable(words):
    for i, w in enumerate(words):
        if not w or _is_noise(w) or w in _PREFIX_WRAPPERS:
            continue
        return w, words[i + 1:]
    return None, []


def _segment_launches(words, token_re):
    exe, rest = _executable(words)
    if exe is None:
        return False
    if token_re.match(_basename(exe)):
        return True
    if _basename(exe) in _RUNNERS:
        if _basename(exe) in ("node", "deno") and any(w in _EVAL_FLAGS for w in rest):
            return False  # inline code (node -e '...'), not a named script
        for w in rest:
            if w.startswith("-") or _is_noise(w):
                continue
            if token_re.match(_basename(w)):
                return True
    return False


def _launches(command, token_re):
    if not command:
        return False
    return any(_segment_launches(words, token_re) for words in _segments(command))


def _is_typecheck(command):
    return _launches(command, _INVOKE_TOKEN)


def _running_detail():
    lines = {}
    for pattern in ("tsc", "tsgo"):
        try:
            out = subprocess.run(
                ["pgrep", "-fl", pattern], capture_output=True, text=True, timeout=5
            ).stdout
        except Exception:
            continue
        for ln in out.splitlines():
            if _launches(_after_pid(ln), _RUN_TOKEN):
                lines[ln.split(" ", 1)[0]] = ln  # dedupe by pid
    return "\n".join(list(lines.values())[:5])


def _after_pid(line):
    parts = line.split(" ", 1)
    return parts[1] if len(parts) > 1 else line


class TypecheckLock(Rule):
    name = "typecheck_lock"

    def applies(self, event):
        if event.tool != "shell":
            return False
        if event.event not in ("pre_tool_use", "post_tool_use"):
            return False
        return _is_typecheck((event.input or {}).get("command"))

    def evaluate(self, event, ctx):
        if event.event == "post_tool_use":
            ctx.locks.release(RESOURCE, event.session_id)
            return None

        running = _running_detail()
        if running:
            return Decision(
                decision=DENY,
                reason=(
                    "Another TypeScript type-check is already running on this machine, so this "
                    "one is blocked to avoid exhausting memory (parallel tsc runs brick local "
                    "compute). Wait for it to finish, then re-run. Already running:\n" + running
                ),
                rule=self.name,
            )

        holder = ctx.locks.acquire(RESOURCE, event.session_id, event.agent, ttl=TTL_SECONDS)
        if holder is not None:
            started = datetime.fromtimestamp(holder["started_at"], timezone.utc).isoformat()
            return Decision(
                decision=DENY,
                reason=(
                    "A TypeScript type-check is already claimed by another agent session "
                    f"({holder['agent']}, started {started}). Parallel tsc runs exhaust memory. "
                    "Wait for it to finish, then re-run."
                ),
                rule=self.name,
            )
        return Decision(decision=ALLOW, rule=self.name)
