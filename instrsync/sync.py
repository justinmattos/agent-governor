"""Engine + CLI for instrsync.

Usage (normally via `bin/govctl`):
    python -m instrsync list
    python -m instrsync show [--agent claude_code|codex|cursor]
    python -m instrsync sync [--dry-run] [--agents claude_code,codex]

Canonical instructions are `instructions/*.md`: agent-neutral markdown, one topic
per file, concatenated in filename order. Optional frontmatter holds one control
key, consumed and never emitted:
    agents: [claude_code, codex, cursor]   restrict which agents receive the file
"""
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from instrsync.targets import ALL_TARGETS, TARGETS, _display

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTRUCTIONS_DIR = os.path.join(ROOT, "instructions")

BEGIN = "<!-- governor:instructions:begin -->"
END = "<!-- governor:instructions:end -->"
NOTE = f"<!-- Generated from {INSTRUCTIONS_DIR} - edit there, then run `bin/govctl instructions-sync`. -->"

_BLOCK_RE = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.DOTALL)
_FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s?(.*)$")


def _split_frontmatter(text):
    """Return (control_dict, body). Frontmatter is consumed and never emitted."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    control = {}
    for raw in m.group(1).split("\n"):
        km = _KEY_RE.match(raw)
        if km and km.group(1) == "agents":
            control["agents"] = _parse_inline_list(km.group(2))
    return control, m.group(2)


def _parse_inline_list(value):
    value = value.split("#", 1)[0].strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [p.strip() for p in value.split(",") if p.strip()]


def discover():
    """Return [(name, path, agents, body)] for every canonical file, in filename order."""
    if not os.path.isdir(INSTRUCTIONS_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(INSTRUCTIONS_DIR)):
        if not fn.endswith(".md") or fn.startswith("."):
            continue
        path = os.path.join(INSTRUCTIONS_DIR, fn)
        with open(path, encoding="utf-8") as fh:
            control, body = _split_frontmatter(fh.read())
        agents = control.get("agents") or ALL_TARGETS
        unknown = [a for a in agents if a not in TARGETS]
        if unknown:
            raise ValueError(f"{fn}: unknown agent(s) in frontmatter: {', '.join(unknown)}")
        out.append((fn[:-3], path, agents, body.strip()))
    return out


def render(agent):
    """The instruction text one agent should see: every file targeting it, in order.

    Returns "" when nothing targets the agent. Safe to call from an adapter at
    session start — it only reads the canonical directory.
    """
    parts = [body for _, _, agents, body in discover() if agent in agents and body]
    return "\n\n".join(parts) + "\n" if parts else ""


def block(body):
    return f"{BEGIN}\n{NOTE}\n{body}{END}\n"


def splice(existing, body):
    """Return `existing` with the managed block replaced, appended, or removed.

    Text outside the block is the user's own and is returned byte-for-byte.
    """
    new_block = block(body) if body else ""
    if _BLOCK_RE.search(existing):
        return _BLOCK_RE.sub(lambda _m: new_block, existing, count=1)
    if not new_block or not existing:
        return new_block or existing
    if existing.endswith("\n\n"):
        sep = ""
    elif existing.endswith("\n"):
        sep = "\n"
    else:
        sep = "\n\n"
    return existing + sep + new_block


def emit(target, dry_run=False):
    """Deliver the rendered instructions to one agent. Returns a status string."""
    body = render(target.name)
    if target.kind == "hook":
        return target.check(body)

    path = target.path()
    try:
        with open(path, encoding="utf-8") as fh:
            existing = fh.read()
        existed = True
    except FileNotFoundError:
        existing, existed = "", False

    new = splice(existing, body)
    if new == existing:
        return f"unchanged {_display(path)}"
    if not body:
        verb = ("remove block from", "removed block from")
    elif not existed:
        verb = ("create", "created")
    elif _BLOCK_RE.search(existing):
        verb = ("update block in", "updated block in")
    else:
        verb = ("append block to", "appended block to")
    if dry_run:
        return f"would {verb[0]} {_display(path)}"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    _atomic_write(path, new, existed)
    return f"{verb[1]} {_display(path)}"


def _atomic_write(path, content, preserve_mode):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    if preserve_mode:
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def cmd_list(_):
    items = discover()
    if not items:
        print("no canonical instructions in", INSTRUCTIONS_DIR)
    for name, _, agents, body in items:
        print(f"  {name:28} -> {', '.join(agents)}  ({len(body)} bytes)")
    print("targets:")
    for t in TARGETS.values():
        print(f"  {t.label:12} {t.describe()}")
    return 0


def cmd_show(argv):
    agent = _opt(argv, "--agent") or "claude_code"
    if agent not in TARGETS:
        print(f"unknown agent {agent!r}; one of {', '.join(ALL_TARGETS)}", file=sys.stderr)
        return 1
    body = render(agent)
    if not body:
        print(f"(nothing targets {TARGETS[agent].label})")
        return 0
    sys.stdout.write(block(body) if TARGETS[agent].kind == "file" else body)
    return 0


def cmd_sync(argv):
    dry = "--dry-run" in argv
    agents_filter = _opt(argv, "--agents")
    wanted = agents_filter.split(",") if agents_filter else ALL_TARGETS
    unknown = [a for a in wanted if a not in TARGETS]
    if unknown:
        print("unknown agent(s):", ", ".join(unknown), file=sys.stderr)
        return 1
    try:
        discover()
    except ValueError as exc:
        print(f"  SKIP: {exc}", file=sys.stderr)
        return 1
    for agent in wanted:
        target = TARGETS[agent]
        print(f"  {target.label:12} {emit(target, dry_run=dry)}")
    verb = "would deliver" if dry else "delivered"
    print(f"{verb} {len(discover())} instruction file(s) to {len(wanted)} agent(s)")
    return 0


def _opt(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


COMMANDS = {"list": cmd_list, "show": cmd_show, "sync": cmd_sync}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        print("usage: instrsync {list | show [--agent x] | sync [--dry-run] [--agents x,y]}",
              file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main())
