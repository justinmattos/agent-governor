import os
import re

from ..engine import ASK, Decision
from .base import Rule
from ._shell import _segments, _tokens

# MCP credentials live in the login keychain (profilesync/secrets.py) and are fetched
# by the server launchers, which agents never run through their own shell. An agent
# shell that reads them back out is asking a human first. Pattern-matched, so
# `python -c` indirection gets past it; it catches the ordinary ways in and logs them.
KEYCHAIN_READS = {"find-generic-password", "find-internet-password"}
KEYCHAIN_DUMPS = {"dump-keychain", "export", "export-identities"}
REVEAL_FLAGS = {"-w", "-g"}
BACKUP = re.compile(r"\.bak-govd-\d")


def _reason(command):
    for segment in _segments(command):
        toks = _tokens(segment)
        if not toks:
            continue
        prog = os.path.basename(toks[0])
        args = toks[1:]
        if prog == "security" and args:
            sub = args[0]
            if sub in KEYCHAIN_DUMPS:
                return f"dumps keychain contents (`security {sub}`)"
            if sub in KEYCHAIN_READS and REVEAL_FLAGS & set(args[1:]):
                return f"prints a keychain password (`security {sub}`)"
        if prog == "govctl" and args and args[0] == "mcp-headers":
            return "prints an MCP server's credential headers (`govctl mcp-headers`)"
        if any(BACKUP.search(t) for t in toks):
            return "touches a governor config backup, which holds MCP credentials"
    return None


class SecretReads(Rule):
    name = "secret_reads"

    def applies(self, event):
        return event.event == "pre_tool_use" and event.tool == "shell"

    def evaluate(self, event, ctx):
        what = _reason((event.input or {}).get("command") or "")
        if not what:
            return None
        return Decision(
            decision=ASK,
            reason=f"govd: this command {what}. Credentials stay out of agent context unless a human approves.",
            rule=self.name,
        )
