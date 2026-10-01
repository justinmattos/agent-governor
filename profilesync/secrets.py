"""MCP server credentials in the macOS login keychain.

A registry value can be a reference, `{"keychain": "<account>"}`, instead of the
secret itself. The secret lives in the login keychain as a generic password under
the service `governor-mcp`, and is fetched only when a server starts:

- stdio servers run through `govctl mcp-launch <server>`, which resolves the
  references in `env` and replaces itself with the real server process;
- HTTP servers get their headers from `govctl mcp-headers <server>` (Claude Code's
  `headersHelper`), or from environment variables `govctl profile` sets (Codex).

`import_inline` moves the secrets a registry still holds inline into the keychain
and rewrites the registry with references. Secrets never pass through argv: writes go
through `security -i` on stdin, and reads come back on stdout.
"""
import json
import os
import re
import subprocess

SERVICE = "governor-mcp"
# Env keys whose values are credentials; every header value is treated as one.
_SECRET_ENV = re.compile(r"(?i)(string|token|key|secret|passw|auth|credential|uri)")


def is_ref(value):
    return isinstance(value, dict) and set(value) == {"keychain"}


def get(account):
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        raise KeyError(f"no keychain item for service {SERVICE}, account {account}")
    return proc.stdout.rstrip("\n")


def _quote(value):
    if any(c in value for c in "\"\\\n\r"):
        raise ValueError("value contains a quote, backslash or newline, which `security -i` can't take")
    return '"' + value + '"'


def put(account, value):
    command = f"add-generic-password -U -s {SERVICE} -a {_quote(account)} -w {_quote(value)}\n"
    proc = subprocess.run(["security", "-i"], input=command, capture_output=True, text=True, timeout=15)
    if proc.returncode != 0 or get(account) != value:
        raise RuntimeError(f"could not store keychain item {account}: {proc.stderr.strip()}")


def delete(account):
    subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", account],
                   capture_output=True, timeout=15)


def resolve(mapping):
    """A copy of an env/headers mapping with every keychain reference replaced by its secret."""
    return {k: get(v["keychain"]) if is_ref(v) else v for k, v in (mapping or {}).items()}


def has_refs(definition):
    return any(is_ref(v) for key in ("env", "headers") for v in (definition.get(key) or {}).values())


def import_inline(registry, dry_run=False):
    """Move inline secrets into the keychain. Returns [(server, field, account)] moved."""
    moved = []
    for server, d in (registry.get("servers") or {}).items():
        for key in ("env", "headers"):
            for field, value in list((d.get(key) or {}).items()):
                if is_ref(value) or not isinstance(value, str):
                    continue
                if key == "env" and not _SECRET_ENV.search(field):
                    continue
                account = f"{server}/{field}"
                if not dry_run:
                    put(account, value)
                    d[key][field] = {"keychain": account}
                moved.append((server, f"{key}.{field}", account))
    return moved


def env_name(server, header):
    """The environment variable `govctl profile --agent codex` sets for one header."""
    return "GOVD_MCP_" + re.sub(r"[^A-Za-z0-9]", "_", f"{server}_{header}").upper()
