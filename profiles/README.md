# profiles

Agent profiles: named bundles of MCP servers that run as a worker your main session
delegates to, or as a session of their own (`govctl profile <name>`). Personal
profiles (`<name>.local.md`) and the server registry (`servers.local.json`, which
holds credentials) are gitignored. Start from the templates in
[`examples/profiles/`](../examples/profiles/) and see the README's
[Profiles](../README.md#profilesync--governing-mcp-servers) section.
