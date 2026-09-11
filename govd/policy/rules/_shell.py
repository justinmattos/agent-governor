"""Shared shell-command parsing helpers.

Extracted so the structural rules (`protect_governor`, `dangerous_bash`) do not
import from `prefer_graphite`, which is a personal, gitignored rule on some machines
and absent on others. Anything every install needs to parse a command line lives here,
in committed code.
"""
import re
import shlex

# Split a command line into segments on shell operators / pipes / subshell
# boundaries, so each `git ...` invocation in a compound command is seen on its own.
# Quotes are handled per-segment by shlex; a rare operator inside quotes may mis-split,
# but classification keys off the segment's leading program either way.
_SPLIT = re.compile(r"&&|\|\||[|;\n&()]")


def _segments(command):
    return [s.strip() for s in _SPLIT.split(command) if s.strip()]


def _tokens(segment):
    try:
        toks = shlex.split(segment)
    except ValueError:
        toks = segment.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in ("sudo", "command", "env", "nohup"):
            i += 1
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t):  # leading VAR=value
            i += 1
            continue
        break
    return toks[i:]
