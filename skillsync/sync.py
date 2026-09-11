"""Engine + CLI for skillsync.

Usage (normally via `bin/govctl`):
    python -m skillsync list
    python -m skillsync sync [--dry-run] [--only name,name] [--agents claude_code,codex]

A canonical skill is a directory under `skills/`:
    skills/<name>/SKILL.md          required — frontmatter + agent-neutral body
    skills/<name>/agents/<agent>.md  optional — mechanics appended for that agent
    skills/<name>/references/…        optional — copied verbatim next to SKILL.md

SKILL.md frontmatter is plain `key: value` scalars. One control key is consumed
by skillsync and never emitted:
    agents: [claude_code, codex, cursor]   restrict which agents receive the skill
"""
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skillsync.targets import ALL_TARGETS, TARGETS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(ROOT, "skills")
MARKER = ".skillsync"

_FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s?(.*)$")


def _split_frontmatter(text):
    """Return (ordered [(key, raw_line)], control_dict, body)."""
    m = _FM_RE.match(text)
    if not m:
        return [], {}, text
    block, body = m.group(1), m.group(2)
    lines, control = [], {}
    for raw in block.split("\n"):
        km = _KEY_RE.match(raw)
        if not km:
            # continuation / comment / blank — keep attached to prior key line
            if lines:
                lines[-1] = (lines[-1][0], lines[-1][1] + "\n" + raw)
            continue
        key, value = km.group(1), km.group(2).strip()
        if key == "agents":
            control["agents"] = _parse_inline_list(value)
            continue
        lines.append((key, raw))
    return lines, control, body


def _parse_inline_list(value):
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [p.strip() for p in value.split(",") if p.strip()]


def _render_frontmatter(lines, keep_keys):
    kept = [raw for key, raw in lines if key in keep_keys]
    return "---\n" + "\n".join(kept) + "\n---\n"


def discover():
    """Yield (skill_name, dir) for each canonical skill (a dir with a SKILL.md).

    A `<name>.local/` dir is a personal, gitignored skill: it materializes under the
    bare `<name>` so it is invoked exactly like a shared skill (`/create-pr`), and a
    fresh clone simply has none.
    """
    if not os.path.isdir(SKILLS_DIR):
        return []
    out = []
    for name in sorted(os.listdir(SKILLS_DIR)):
        path = os.path.join(SKILLS_DIR, name)
        if os.path.isfile(os.path.join(path, "SKILL.md")):
            skill_name = name[:-len(".local")] if name.endswith(".local") else name
            out.append((skill_name, path))
    return out


def _targets_for(control, agents_filter):
    wanted = control.get("agents") or ALL_TARGETS
    unknown = [a for a in wanted if a not in TARGETS]
    if unknown:
        raise ValueError(f"unknown agent(s) in frontmatter: {', '.join(unknown)}")
    if agents_filter:
        wanted = [a for a in wanted if a in agents_filter]
    return wanted


def emit(name, src_dir, target, dry_run=False):
    """Materialize one canonical skill into one agent. Returns a status string."""
    with open(os.path.join(src_dir, "SKILL.md")) as fh:
        text = fh.read()
    lines, control, body = _split_frontmatter(text)

    mech = os.path.join(src_dir, "agents", target.name + ".md")
    if os.path.isfile(mech):
        with open(mech) as fh:
            body = body.rstrip() + "\n\n---\n\n" + fh.read().lstrip()

    out = _render_frontmatter(lines, target.keep_keys) + "\n" + body.lstrip("\n")
    dest = target.skill_dir(name)

    if dry_run:
        return f"would write {dest}/SKILL.md ({len(out)} bytes)"

    os.makedirs(dest, exist_ok=True)
    _atomic_write(os.path.join(dest, "SKILL.md"), out)

    refs = os.path.join(src_dir, "references")
    if os.path.isdir(refs):
        dst_refs = os.path.join(dest, "references")
        shutil.rmtree(dst_refs, ignore_errors=True)
        shutil.copytree(refs, dst_refs)

    _atomic_write(os.path.join(dest, MARKER), json.dumps({
        "skill": name, "source": src_dir, "synced_at": int(time.time()),
    }) + "\n")

    if target.register:
        target.register(target, name)
    return f"wrote {dest}/SKILL.md"


def _atomic_write(path, content):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(content)
    os.replace(tmp, path)


def cmd_list(_):
    skills = discover()
    if not skills:
        print("no canonical skills in", SKILLS_DIR)
        return 0
    for name, path in skills:
        with open(os.path.join(path, "SKILL.md")) as fh:
            _, control, _ = _split_frontmatter(fh.read())
        agents = control.get("agents") or ALL_TARGETS
        mech = []
        adir = os.path.join(path, "agents")
        if os.path.isdir(adir):
            mech = [f[:-3] for f in sorted(os.listdir(adir)) if f.endswith(".md")]
        extra = " +mechanics[" + ",".join(mech) + "]" if mech else ""
        local = "  (personal)" if os.path.basename(path).endswith(".local") else ""
        print(f"  {name:28} -> {', '.join(agents)}{extra}{local}")
    return 0


def cmd_sync(argv):
    dry = "--dry-run" in argv
    only = _opt(argv, "--only")
    agents_filter = _opt(argv, "--agents")
    only = set(only.split(",")) if only else None
    agents_filter = set(agents_filter.split(",")) if agents_filter else None

    skills = discover()
    if only:
        skills = [(n, p) for n, p in skills if n in only]
        missing = only - {n for n, _ in skills}
        if missing:
            print("no such skill(s):", ", ".join(sorted(missing)), file=sys.stderr)
            return 1
    if not skills:
        print("nothing to sync")
        return 0

    count = 0
    for name, path in skills:
        with open(os.path.join(path, "SKILL.md")) as fh:
            _, control, _ = _split_frontmatter(fh.read())
        try:
            wanted = _targets_for(control, agents_filter)
        except ValueError as exc:
            print(f"  SKIP {name}: {exc}", file=sys.stderr)
            continue
        for agent in wanted:
            status = emit(name, path, TARGETS[agent], dry_run=dry)
            print(f"  {name} -> {TARGETS[agent].label}: {status}")
            count += 1
    verb = "would sync" if dry else "synced"
    print(f"{verb} {len(skills)} skill(s) across {count} target(s)")
    return 0


def _opt(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


COMMANDS = {"list": cmd_list, "sync": cmd_sync}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in COMMANDS:
        print("usage: skillsync {list | sync} [--dry-run] [--only a,b] [--agents x,y]",
              file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main())
