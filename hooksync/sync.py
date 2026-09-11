"""Engine + CLI for hooksync.

Usage (normally via `bin/govctl`):
    python -m hooksync list
    python -m hooksync sync [--dry-run] [--agents claude_code,codex]

The canonical `install/*.json` is a template: its `{python}` and `{governor_root}`
placeholders are resolved against this checkout before the merge, so any clone wires
itself correctly. Each agent's live hook settings file is the user's own: a sync
merges only the governor's hook entries into it — entries whose command references the agent's
governor adapter — replacing any it already installed and leaving every other key
and every hook the user added byte-for-byte in place. Re-running is idempotent.
"""
import copy
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hooksync.targets import ALL_TARGETS, ROOT, TARGETS, _display


def _load(path):
    """Return (data, existed). A missing file is empty; malformed JSON raises."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), True
    except FileNotFoundError:
        return {}, False


def render(text):
    """Fill a canonical config's placeholders in for this checkout.

    `install/*.json` ships `{python} {governor_root}/adapters/<agent>.py` instead of a
    real path, so the repo works from wherever it is cloned. Both tokens are resolved
    here, at sync time: the interpreter running the sync, and this checkout's own root.
    """
    return text.replace("{governor_root}", ROOT).replace("{python}", sys.executable)


def _load_source(path):
    """Return (data, existed) for a canonical config, placeholders resolved."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.loads(render(fh.read())), True
    except FileNotFoundError:
        return {}, False


def _commands(node):
    """Every `command` string inside a hook entry, at any nesting depth."""
    out = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "command" and isinstance(value, str):
                out.append(value)
            else:
                out += _commands(value)
    elif isinstance(node, list):
        for item in node:
            out += _commands(item)
    return out


def _is_ours(entry, adapter):
    return adapter in json.dumps(entry)


def merge(dest, source, adapter):
    """Return (new_dest, changed_events).

    Only the governor's own entries (those referencing `adapter`) are added or
    replaced, per event. Other keys, other events, and the user's own hooks in a
    shared event are preserved.
    """
    new = copy.deepcopy(dest) if dest else {}
    if "version" in source and "version" not in new:
        new["version"] = source["version"]
    src_hooks = source.get("hooks") or {}
    dst_hooks = new.setdefault("hooks", {})
    changed = []
    for event, groups in src_hooks.items():
        before = json.dumps(dst_hooks.get(event, []), sort_keys=True)
        kept = [e for e in dst_hooks.get(event, []) if not _is_ours(e, adapter)]
        dst_hooks[event] = kept + copy.deepcopy(groups)
        if json.dumps(dst_hooks[event], sort_keys=True) != before:
            changed.append(event)
    return new, changed


def _atomic_write(path, content, preserve_mode):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    if preserve_mode:
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def emit(target, dry_run=False):
    """Install one agent's governor hooks. Returns a status string."""
    try:
        source, has_source = _load_source(target.source_path())
    except ValueError:
        return f"SKIP: {_display(target.source_path())} is not valid JSON"
    if not has_source:
        return f"SKIP: missing {_display(target.source_path())}"
    try:
        dest, existed = _load(target.dest_path())
    except ValueError:
        return f"SKIP: {_display(target.dest_path())} is not valid JSON — fix it by hand"

    new, changed = merge(dest, source, target.adapter)
    if new == dest:
        return f"unchanged {_display(target.dest_path())}"
    events = ", ".join(changed) if changed else "version"
    if dry_run:
        return f"would {'create' if not existed else 'update'} {_display(target.dest_path())} ({events})"
    os.makedirs(os.path.dirname(target.dest_path()), exist_ok=True)
    _atomic_write(target.dest_path(), json.dumps(new, indent=2) + "\n", existed)
    return f"{'created' if not existed else 'updated'} {_display(target.dest_path())} ({events})"


def wired(target):
    """True when the dest already carries this checkout's exact governor commands."""
    try:
        source, has_source = _load_source(target.source_path())
        dest, existed = _load(target.dest_path())
    except ValueError:
        return False
    if not has_source or not existed:
        return False
    dst_hooks = dest.get("hooks") or {}
    for event, groups in (source.get("hooks") or {}).items():
        # Compare the whole rendered command, not just the adapter's name: an entry
        # left behind by a different checkout carries the same name at a path that no
        # longer exists, and would otherwise report as wired while failing open.
        if not set(_commands(groups)) <= set(_commands(dst_hooks.get(event, []))):
            return False
    return True


def cmd_list(_):
    for t in TARGETS.values():
        print(f"  {t.label:12} {'wired ' if wired(t) else 'MISSING'}  {t.describe()}")
    return 0


def _opt(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def cmd_sync(argv):
    dry = "--dry-run" in argv
    agents_filter = _opt(argv, "--agents")
    wanted = agents_filter.split(",") if agents_filter else ALL_TARGETS
    unknown = [a for a in wanted if a not in TARGETS]
    if unknown:
        print("unknown agent(s):", ", ".join(unknown), file=sys.stderr)
        return 1
    for agent in wanted:
        print(f"  {TARGETS[agent].label:12} {emit(TARGETS[agent], dry_run=dry)}")
    print(f"{'would wire' if dry else 'wired'} governor hooks into {len(wanted)} agent(s)")
    return 0


COMMANDS = {"list": cmd_list, "sync": cmd_sync}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        print("usage: hooksync {list | sync [--dry-run] [--agents x,y]}", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main())
