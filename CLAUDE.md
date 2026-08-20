# Claude Code

Work in this repo is tracked in **bd (beads)** — vendored at `vendor/beads`,
built to `./bin/bd` (v1.2.2). The `SessionStart` hook in
`.claude/settings.json` already put `<repo>/bin` first on PATH for every Bash
call; if `command -v bd` disagrees, `export PATH="$PWD/bin:$PATH"`.

Read [AGENT_INSTRUCTIONS.md](AGENT_INSTRUCTIONS.md) and
[docs/RESOLVERS.md](docs/RESOLVERS.md).

```bash
bd prime
bd ready
```

The thing being built is the Humalike API recreation in `spec/`.
`spec/`, `research/`, `sources/` are OpenKnowledge-governed markdown — use
the `open-knowledge` MCP tools for them, not native `Read`/`Edit`.
