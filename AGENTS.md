# Agent contract

Work in this repo is tracked in **bd (beads)**, vendored at `vendor/beads`
and built to `./bin/bd` (v1.2.2). The thing being built is the Humalike API
recreation in `spec/`.

Read [AGENT_INSTRUCTIONS.md](AGENT_INSTRUCTIONS.md) and
[docs/RESOLVERS.md](docs/RESOLVERS.md).

```bash
export PATH="$PWD/bin:$PATH"   # hosts with the project hooks already did this
bd prime
bd ready
```

`./bin/bd` is the only beads binary this repo trusts. `./scripts/bd` will not
fall through to PATH. If `./bin/bd` is missing: `make bd`.

`spec/`, `research/`, `sources/` are OpenKnowledge-governed markdown — use
the `open-knowledge` MCP tools for them, not native file tools.
