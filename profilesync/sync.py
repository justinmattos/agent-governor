"""Engine + CLI for profilesync.

Usage (normally via `bin/govctl`):
    python -m profilesync.sync list
    python -m profilesync.sync sync [--dry-run] [--only name,name]
    python -m profilesync.sync run <profile> [--agent claude_code|codex] [agent args...]

A profile is `profiles/<name>.md` (shared) or `profiles/<name>.local.md` (personal,
gitignored): `key: value` frontmatter plus a body that becomes the worker's brief.
    name: prod-investigator
    description: when the main session should delegate here
    servers: [mongodb-prod, internal-api-prod] names from the server registry
    readonly: true                            block each server's `write_tools`
    model: sonnet                             optional
    tools: [Read, Grep, mcp__mongodb-prod]     optional allowlist; omit to inherit

Server definitions live in `profiles/servers.local.json` (gitignored — it holds
credentials), in the same schema as a `.mcp.json` entry plus two governor keys that
are never emitted: `write_tools` (tool names `readonly` blocks) and `writable`.
Its top-level `retire` list names older everyday entries the registry replaces.
Every registry server is profile-owned: a sync removes it, and anything under
`retire`, from each agent's everyday config.
"""
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from govd import config
from profilesync import secrets
from profilesync.targets import ALL_TARGETS, TARGETS, _atomic_write, _claude_def

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_DIR = os.path.join(ROOT, "profiles")
REGISTRY = os.path.join(PROFILES_DIR, "servers.local.json")
MANIFEST = os.path.join(config.GOVD_HOME, "profilesync.json")
RUN_DIR = os.path.join(config.GOVD_HOME, "profiles")
GOVERNOR_KEYS = {"write_tools", "writable"}

_FM_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s?(.*)$")


def _value(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [p.strip().strip("\"'") for p in raw[1:-1].split(",") if p.strip()]
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    return raw.strip("\"'")


def parse(path):
    with open(path) as fh:
        m = _FM_RE.match(fh.read())
    if not m:
        raise ValueError(f"{path}: no frontmatter")
    profile = {"body": m.group(2)}
    for line in m.group(1).split("\n"):
        km = _KEY_RE.match(line)
        if km:
            profile[km.group(1)] = _value(km.group(2))
    for key in ("name", "description", "servers"):
        if not profile.get(key):
            raise ValueError(f"{path}: missing `{key}`")
    return profile


def discover():
    if not os.path.isdir(PROFILES_DIR):
        return []
    return [os.path.join(PROFILES_DIR, f) for f in sorted(os.listdir(PROFILES_DIR))
            if f.endswith(".md") and f != "README.md"]


def load_registry():
    try:
        with open(REGISTRY) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"servers": {}}


def resolve(profile, registry):
    """(servers to emit, tools to disallow) for one profile."""
    defs = registry.get("servers") or {}
    missing = [s for s in profile["servers"] if s not in defs]
    if missing:
        raise ValueError(f"profile {profile['name']}: unknown server(s) {', '.join(missing)}")
    servers, disallowed = {}, []
    for s in profile["servers"]:
        servers[s] = {k: v for k, v in defs[s].items() if k not in GOVERNOR_KEYS}
        if profile.get("readonly"):
            disallowed += [f"mcp__{s}__{t}" for t in defs[s].get("write_tools") or []]
    return servers, disallowed


def _manifest():
    try:
        with open(MANIFEST) as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}


def generated_paths():
    """Every file a sync has generated, for protect_governor."""
    return [p for t in _manifest().values() for p in t.get("agents", [])]


def sync(dry_run=False, only=None):
    registry = load_registry()
    paths = discover()
    if only:
        paths = [p for p in paths if parse(p)["name"] in only]
    manifest = _manifest()
    for tname in ALL_TARGETS:
        target = TARGETS[tname]
        written = []
        for path in paths:
            profile = parse(path)
            if tname not in (profile.get("agents") or ALL_TARGETS):
                continue
            servers, disallowed = resolve(profile, registry)
            profile["disallowed"] = disallowed
            src = os.path.relpath(path, ROOT)
            dests = target.write(profile, servers, src, dry_run)
            written.extend(dests)
            verb = "would write" if dry_run else "wrote"
            print(f"  {target.label:12} {verb} {', '.join(dests)}  servers: {', '.join(servers)}"
                  + (f"; {len(disallowed)} write tool(s) blocked" if disallowed else ""))
        previous = (manifest.get(tname) or {}).get("agents", [])
        if not only:
            for stale in target.remove_stale(previous, written, dry_run):
                print(f"  {target.label:12} {'would remove' if dry_run else 'removed'} stale {stale}")
            kept = written
        else:
            kept = sorted(set(previous) | set(written))
        owned = list(registry.get("servers") or {}) + list(registry.get("retire") or [])
        removed = target.retire_everyday(owned, dry_run)
        if removed:
            print(f"  {target.label:12} {'would remove' if dry_run else 'removed'} from everyday config: {', '.join(removed)}")
        manifest[tname] = {"agents": kept}
    if not dry_run:
        config.ensure_home()
        _atomic_write(MANIFEST, json.dumps(manifest, indent=2))
    return 0


def list_profiles():
    registry = load_registry()
    print(f"registry: {os.path.relpath(REGISTRY, ROOT)} ({len(registry.get('servers') or {})} servers)")
    for path in discover():
        p = parse(path)
        flags = " readonly" if p.get("readonly") else ""
        local = " (local)" if path.endswith(".local.md") else ""
        print(f"  {p['name']:24} {', '.join(p['servers'])}{flags}{local}")
    return 0


def _codex_bin():
    found = shutil.which("codex") or os.environ.get("CODEX_CLI_PATH")
    return found or "/Applications/ChatGPT.app/Contents/Resources/codex"


def run(name, extra):
    """Replace this process with an agent session that has only the profile's servers.

    Claude Code gets them through --strict-mcp-config. Codex layers the synced
    `<name>.config.toml` profile over its base config, so its remaining everyday
    servers stay loaded alongside.
    """
    agent = "claude_code"
    if "--agent" in extra:
        i = extra.index("--agent")
        agent, extra = extra[i + 1], extra[:i] + extra[i + 2:]
    if agent == "codex":
        codex = _codex_bin()
        env = dict(os.environ)
        for server in profile_servers(name):
            d = load_registry()["servers"][server]
            for header, value in (d.get("headers") or {}).items():
                if secrets.is_ref(value):
                    env[secrets.env_name(server, header)] = secrets.get(value["keychain"])
        os.execve(codex, [codex, "-p", name] + extra, env)
    registry = load_registry()
    match = [p for p in (parse(x) for x in discover()) if p["name"] == name]
    if not match:
        print(f"no profile named {name}", file=sys.stderr)
        return 2
    profile = match[0]
    servers, disallowed = resolve(profile, registry)
    config.ensure_home()
    mcp_file = os.path.join(RUN_DIR, name + ".mcp.json")
    _atomic_write(mcp_file, json.dumps({"mcpServers": {n: _claude_def(n, d) for n, d in servers.items()}}, indent=2))
    argv = ["claude", "--strict-mcp-config", "--mcp-config", mcp_file,
            "--append-system-prompt", profile["body"].strip()]
    if disallowed:
        argv += ["--disallowedTools", ",".join(disallowed)]
    if profile.get("model"):
        argv += ["--model", profile["model"]]
    os.execvp("claude", argv + extra)


def profile_servers(name):
    match = [p for p in (parse(x) for x in discover()) if p["name"] == name]
    if not match:
        raise SystemExit(f"no profile named {name}")
    return match[0]["servers"]


def launch(server):
    """Replace this process with a stdio server, its keychain references resolved into env."""
    d = (load_registry().get("servers") or {})[server]
    env = dict(os.environ)
    env.update(secrets.resolve(d.get("env")))
    os.execve(d["command"], [d["command"]] + list(d.get("args") or []), env)


def headers(server):
    """Print one HTTP server's headers as JSON, for Claude Code's headersHelper."""
    d = (load_registry().get("servers") or {})[server]
    print(json.dumps(secrets.resolve(d.get("headers"))))
    return 0


def import_secrets(dry_run=False):
    registry = load_registry()
    moved = secrets.import_inline(registry, dry_run=dry_run)
    for server, field, account in moved:
        print(f"  {'would move' if dry_run else 'moved'} {server} {field} -> keychain {secrets.SERVICE}/{account}")
    if moved and not dry_run:
        _atomic_write(REGISTRY, json.dumps(registry, indent=2))
        print(f"{len(moved)} secret(s) moved; {os.path.relpath(REGISTRY, ROOT)} now holds references only. Run `govctl profiles-sync`.")
    elif not moved:
        print("no inline secrets left in the registry")
    return 0


def main(argv):
    cmd = argv[0] if argv else ""
    rest = argv[1:]
    if cmd == "list":
        return list_profiles()
    if cmd == "sync":
        only = None
        if "--only" in rest:
            only = set(rest[rest.index("--only") + 1].split(","))
        return sync(dry_run="--dry-run" in rest, only=only)
    if cmd == "run" and rest:
        return run(rest[0], rest[1:])
    if cmd == "launch" and rest:
        return launch(rest[0])
    if cmd == "headers" and rest:
        return headers(rest[0])
    if cmd == "import-secrets":
        return import_secrets(dry_run="--dry-run" in rest)
    print("usage: profilesync {list | sync [--dry-run] [--only a,b] | run <profile> [--agent claude_code|codex] [args]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
