"""Publish the skill library to a git repo as a Claude Code + Codex plugin marketplace.

Cloud agent platforms (e.g. Niteshift) install plugins from a marketplace repo, not from
`~/.claude/skills`. This builds one repo that is both marketplaces at once:

    .claude-plugin/marketplace.json        Claude Code marketplace
    plugins/claude-code/.claude-plugin/plugin.json
    plugins/claude-code/skills/<name>/      skills shaped for Claude Code
    .agents/plugins/marketplace.json        Codex marketplace
    plugins/codex/plugin.json
    plugins/codex/skills/<name>/            skills shaped for Codex
    plugins/hooks/                          `<plugin>-hooks`, loads in both agents

Each skill goes through the same `emit` as a local sync, so the published copy matches
what that agent runs locally. The hooks plugin bundles govd, its rules, the adapters
and the standing instructions; its hooks run the adapters in embedded mode
(adapters/embedded.py), which start the daemon inside the sandbox. Personal skills,
rules and instructions (`*.local*`) are included in both, so the remote should be
private.

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
GOVERNOR_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CHECKOUT = "~/.govd/skills-publish"
DEFAULT_PLUGIN = "governor"
# Paths in the checkout this module owns; rebuilt from scratch on every publish.
MANAGED = (".claude-plugin", ".agents", "plugins", "README.md")
# (target id, plugin subdir) for each marketplace in the repo.
PLUGIN_DIRS = (("claude_code", "claude-code"), ("codex", "codex"))
# What the hooks plugin bundles from this repo: the daemon, the instructions and their
# renderer, and the adapters of the agents that run in cloud sandboxes.
BUNDLE_DIRS = ("govd", "instrsync", "instructions")
BUNDLE_ADAPTERS = ("claude_code.py", "codex.py", "embedded.py")


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
    _write_json(os.path.join(checkout, "plugins", "codex", "plugin.json"),
                {"name": plugin, "version": "1.0.0", "description": description})

    hooks = plugin + "-hooks"
    hooks_description = ("govd policy hooks, run inside the sandbox, plus standing instructions "
                         "injected at session start.")
    build_hooks_plugin(os.path.join(checkout, "plugins", "hooks"), hooks, hooks_description)

    entries = [(plugin, "claude-code", "codex", description),
               (hooks, "hooks", "hooks", hooks_description)]
    _write_json(os.path.join(checkout, ".claude-plugin", "marketplace.json"), {
        "name": plugin,
        "description": description,
        "owner": {"name": plugin},
        "plugins": [{"name": name, "source": f"./plugins/{claude_dir}", "description": desc}
                    for name, claude_dir, _, desc in entries],
    })
    _write_json(os.path.join(checkout, ".agents", "plugins", "marketplace.json"), {
        "name": plugin,
        "plugins": [{
            "name": name,
            "source": {"source": "local", "path": f"./plugins/{codex_dir}"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        } for name, _, codex_dir, _ in entries],
    })
    with open(os.path.join(checkout, "README.md"), "w") as fh:
        fh.write(
            f"# {plugin}\n\n"
            "Generated by `skillsync` from the governor repo — do not edit here; edits are\n"
            "overwritten on the next `govctl skills-sync`.\n\n"
            f"A plugin marketplace named `{plugin}` for both Claude Code and Codex:\n\n"
            f"- `{plugin}@{plugin}` — the skill library.\n"
            f"- `{hooks}@{plugin}` — govd's policy hooks and standing instructions. They carry\n"
            "  personal rules and instructions, so enable this only where they should apply.\n"
        )


def _hook_config(template, root_var):
    """A plugin hooks file from an install/ template, plus a SessionStart entry.

    Each command runs the bundled adapter in embedded mode; SessionStart starts the
    daemon and injects the standing instructions.
    """
    with open(os.path.join(GOVERNOR_ROOT, "install", template)) as fh:
        config = json.load(fh)
    prefix = f'GOVD_EMBEDDED=1 python3 "${{{root_var}}}"'
    for entries in config["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                hook["command"] = hook["command"].replace("{python} {governor_root}", prefix)
    adapter = config["hooks"]["PreToolUse"][0]["hooks"][0]
    config["hooks"]["SessionStart"] = [{"hooks": [dict(adapter)]}]
    return config


def build_hooks_plugin(dest, name, description):
    """One plugin dir that loads in both agents: Claude Code reads `.claude-plugin/` and
    `hooks/hooks.json`; Codex reads the root `plugin.json`, pointed at `hooks/codex.json`."""
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "config.local.json")
    for sub in BUNDLE_DIRS:
        shutil.copytree(os.path.join(GOVERNOR_ROOT, sub), os.path.join(dest, sub), ignore=ignore)
    os.makedirs(os.path.join(dest, "adapters"))
    for fn in BUNDLE_ADAPTERS:
        shutil.copy2(os.path.join(GOVERNOR_ROOT, "adapters", fn), os.path.join(dest, "adapters", fn))

    _write_json(os.path.join(dest, ".claude-plugin", "plugin.json"),
                {"name": name, "description": description})
    _write_json(os.path.join(dest, "hooks", "hooks.json"),
                _hook_config("claude-code.settings.json", "CLAUDE_PLUGIN_ROOT"))
    _write_json(os.path.join(dest, "plugin.json"), {
        "name": name, "version": "1.0.0", "description": description,
        "extensions": {"com.openai": {"hooks": "./hooks/codex.json"}},
    })
    _write_json(os.path.join(dest, "hooks", "codex.json"),
                _hook_config("codex.hooks.json", "PLUGIN_ROOT"))


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
