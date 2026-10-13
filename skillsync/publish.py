"""Publish the skill library to a git repo as a Claude Code + Codex plugin marketplace.

Cloud agent platforms (e.g. Niteshift) install plugins from a marketplace repo, not from
`~/.claude/skills`. This builds one repo that is both marketplaces at once:

    .claude-plugin/marketplace.json        Claude Code marketplace
    plugins/claude-code/.claude-plugin/plugin.json
    plugins/claude-code/skills/<name>/      skills shaped for Claude Code
    .agents/plugins/marketplace.json        Codex marketplace
    plugins/codex/plugin.json
    plugins/codex/skills/<name>/            skills shaped for Codex

Each skill goes through the same `emit` as a local sync, so the published copy matches
what that agent runs locally. Personal `<name>.local/` skills are included, so the remote
should be private.

Configured by the gitignored `skillsync/config.local.json`; with no config, publishing
is off:

    {"publish": {"remote": "git@github.com:you/agent-skills.git",
                 "checkout": "~/.govd/skills-publish",
                 "plugin": "governor"}}
"""
import json
import os
import shutil
import subprocess

from skillsync.targets import TARGETS, Target

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.local.json")
DEFAULT_CHECKOUT = "~/.govd/skills-publish"
DEFAULT_PLUGIN = "governor"
# Paths in the checkout this module owns; rebuilt from scratch on every publish.
MANAGED = (".claude-plugin", ".agents", "plugins", "README.md")
# (target id, plugin subdir) for each marketplace in the repo.
PLUGIN_DIRS = (("claude_code", "claude-code"), ("codex", "codex"))


def load_config():
    try:
        with open(CONFIG) as fh:
            cfg = json.load(fh).get("publish") or {}
    except FileNotFoundError:
        return None
    if not cfg.get("remote"):
        return None
    cfg["checkout"] = os.path.expanduser(cfg.get("checkout") or DEFAULT_CHECKOUT)
    cfg.setdefault("plugin", DEFAULT_PLUGIN)
    return cfg


def _git(checkout, *args):
    return subprocess.run(["git", "-C", checkout, *args], capture_output=True, text=True)


def _prepare_checkout(cfg):
    """Clone the remote, or bring an existing clone up to date. Returns an error or None."""
    checkout = cfg["checkout"]
    if not os.path.isdir(os.path.join(checkout, ".git")):
        os.makedirs(os.path.dirname(checkout), exist_ok=True)
        r = subprocess.run(["git", "clone", "--quiet", cfg["remote"], checkout],
                           capture_output=True, text=True)
        return r.stderr.strip() or "git clone failed" if r.returncode else None
    if _git(checkout, "rev-parse", "--verify", "--quiet", "HEAD").returncode:
        return None  # freshly created empty repo: nothing to pull yet
    r = _git(checkout, "pull", "--quiet", "--ff-only")
    return r.stderr.strip() or "git pull failed" if r.returncode else None


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def build(cfg, skills, emit, wanted_for):
    """Rebuild the marketplace tree in the checkout from the canonical skills."""
    checkout, plugin = cfg["checkout"], cfg["plugin"]
    for name in MANAGED:
        path = os.path.join(checkout, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)

    description = "Skills published from the governor skill library by skillsync."
    for target_id, subdir in PLUGIN_DIRS:
        base = TARGETS[target_id]
        target = Target(name=base.name, label=base.label,
                        root=os.path.join(checkout, "plugins", subdir, "skills"),
                        keep_keys=base.keep_keys)
        for name, path in skills:
            if target_id in wanted_for(path):
                emit(name, path, target, marker=False)

    _write_json(os.path.join(checkout, "plugins", "claude-code", ".claude-plugin", "plugin.json"),
                {"name": plugin, "description": description})
    _write_json(os.path.join(checkout, ".claude-plugin", "marketplace.json"), {
        "name": plugin,
        "description": description,
        "owner": {"name": plugin},
        "plugins": [{"name": plugin, "source": "./plugins/claude-code",
                     "description": description}],
    })
    _write_json(os.path.join(checkout, "plugins", "codex", "plugin.json"),
                {"name": plugin, "version": "1.0.0", "description": description})
    _write_json(os.path.join(checkout, ".agents", "plugins", "marketplace.json"), {
        "name": plugin,
        "plugins": [{
            "name": plugin,
            "source": {"source": "local", "path": "./plugins/codex"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }],
    })
    with open(os.path.join(checkout, "README.md"), "w") as fh:
        fh.write(
            f"# {plugin} skills\n\n"
            "Generated by `skillsync` from the governor skill library — do not edit here;\n"
            "edits are overwritten on the next `govctl skills-sync`.\n\n"
            "This repo is a plugin marketplace for both Claude Code and Codex:\n\n"
            f"- Claude Code: marketplace `{plugin}`, plugin `{plugin}@{plugin}`\n"
            f"- Codex: marketplace `{plugin}`, plugin `{plugin}@{plugin}`\n"
        )


def publish(skills, emit, wanted_for, dry_run=False):
    """Build and push the marketplace repo. Never fails the local sync; returns a status line."""
    cfg = load_config()
    if not cfg:
        return None
    if dry_run:
        return f"would publish {len(skills)} skill(s) to {cfg['remote']}"
    err = _prepare_checkout(cfg)
    if err:
        return f"WARNING: publish skipped, could not prepare {cfg['checkout']}: {err}"
    build(cfg, skills, emit, wanted_for)

    checkout = cfg["checkout"]
    _git(checkout, "add", "-A")
    if not _git(checkout, "status", "--porcelain").stdout.strip():
        return f"published skills already up to date at {cfg['remote']}"
    names = ", ".join(n for n, _ in skills)
    r = _git(checkout, "commit", "--quiet", "-m", f"skillsync: publish {names}")
    if r.returncode:
        return f"WARNING: publish commit failed: {r.stderr.strip() or r.stdout.strip()}"
    r = _git(checkout, "push", "--quiet", "-u", "origin", "HEAD")
    if r.returncode:
        return f"WARNING: committed in {checkout} but push failed: {r.stderr.strip()}"
    return f"published {len(skills)} skill(s) to {cfg['remote']}"
