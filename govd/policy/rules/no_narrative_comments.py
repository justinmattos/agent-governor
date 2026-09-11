import os
import re
import subprocess

from ..engine import BLOCK, Decision
from .base import Rule

FUNCTIONAL = re.compile(
    r"(eslint-disable|eslint-enable|@ts-expect-error|@ts-ignore|@ts-nocheck|prettier-ignore"
    r"|istanbul ignore|c8 ignore|@deprecated|<reference\s|biome-ignore|oxlint-disable)"
)
COMMENT_START = re.compile(r"^\s*(//|/\*|\*/|\*(?!\*/))")


def _comment_lines(text):
    if not text:
        return []
    return [
        line.strip()
        for line in text.splitlines()
        if COMMENT_START.match(line) and not FUNCTIONAL.search(line)
    ]


def _head_version(path, cwd):
    if not cwd:
        return ""
    rel = os.path.relpath(path, cwd) if os.path.isabs(path) else path
    try:
        return subprocess.run(
            ["git", "show", f"HEAD:./{rel}"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=cwd,
        ).stdout
    except Exception:
        return ""


def _patch_sides(text):
    added, baseline = [], []
    for line in (text or "").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            baseline.append(line[1:])
    return "\n".join(added), "\n".join(baseline)


class NoNarrativeComments(Rule):
    name = "no_narrative_comments"

    def applies(self, event):
        return event.event == "post_tool_use" and event.tool == "file_edit"

    def _gather(self, event):
        data = event.input or {}
        path = data.get("file_path") or data.get("path") or data.get("file") or ""
        added, baseline = [], []
        if "edits" in data:
            for edit in data.get("edits") or []:
                added += _comment_lines(edit.get("new_string"))
                baseline += _comment_lines(edit.get("old_string"))
        elif "new_string" in data:
            added = _comment_lines(data.get("new_string"))
            baseline = _comment_lines(data.get("old_string"))
        elif "content" in data:
            added = _comment_lines(data.get("content"))
            baseline = _comment_lines(_head_version(path, event.cwd))
        elif data.get("patch") or data.get("input"):
            add_text, base_text = _patch_sides(data.get("patch") or data.get("input"))
            added = _comment_lines(add_text)
            baseline = _comment_lines(base_text)
        return path, added, baseline

    def evaluate(self, event, ctx):
        path, added, baseline = self._gather(event)
        if not path.endswith((".ts", ".tsx")):
            return None

        surviving = list(added)
        for line in baseline:
            if line in surviving:
                surviving.remove(line)
        if not surviving:
            return None

        block = "\n".join(f"  {line}" for line in surviving)
        multiline = sum(1 for line in surviving if line.startswith(("/*", "*", "*/")))
        warning = (
            "\nAt least one is a multi-line block or docstring. Those are always wrong here — "
            "if a why needs two lines, it needs one shorter line.\n"
            if multiline
            else ""
        )
        message = (
            f"You just added {len(surviving)} comment line(s) to {path}:\n\n{block}\n{warning}\n"
            "Run the deletion test on each, out loud, before continuing:\n"
            "  Would removing it confuse someone reading this file cold in six months?\n\n"
            "Delete it if it restates the code, names a caller, justifies the change to a "
            "reviewer, labels a step, or cites a ticket/vendor/product. Those belong in the PR "
            "description, not the source. This rule OVERRIDES matching the surrounding file's "
            "comment density — neighbouring docstrings do not license a new one.\n\n"
            "Keep it only for a hidden constraint, a non-obvious invariant, or a magic value's "
            "origin — one line, declarative. Either edit the file to remove them, or state which "
            "test each one passes and why."
        )
        return Decision(decision=BLOCK, reason=message, context=message, rule=self.name)
