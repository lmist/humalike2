# Agent instructions

This is the beads contract for this repo. `AGENTS.md` (Codex, Cursor),
`CLAUDE.md` (Claude Code) and `.cursor/rules/beads.mdc` are short pointers
here.

This repo tracks work in **bd (beads)**. Read this file, then look up rows in
[docs/RESOLVERS.md](docs/RESOLVERS.md). Do not invent a parallel tracker.

```bash
export PATH="$PWD/bin:$PATH"
bd prime
bd ready
```

`./bin/bd` is built from `vendor/beads` (gastownhall/beads **v1.2.2**).
`./scripts/bd` execs that binary and refuses to fall through to Homebrew.
Your host should already have put `<repo>/bin` first on PATH (Claude:
SessionStart hook; Codex / Cursor: PreToolUse command rewrite); if
`command -v bd` says otherwise, run the `export` above.

## What is being built

The clean-room Humalike API recreation specified in `spec/`:

- `spec/00-index.md` — normative index and evidence chain
- `spec/07-implementation-plan.md` — phases 0–8, each with an exit criterion
- `spec/08-parity-and-open-questions.md` — the live conformance gate
  (`tests/realtime`, `tests/intelligence`; exit `0` green, `1` failures,
  `3` credit-depleted = budget blocker, never a regression) and ten open questions
- `research/` — tested digests and paper analyses; `sources/` — preserved corpus

`spec/`, `research/`, `sources/` are **OpenKnowledge-governed** markdown. Read
and edit them only through the `open-knowledge` MCP tools (`exec("cat …")`,
`edit`, `write`). Native `Read`/`Grep`/`sed` on those files bypasses the CRDT.
Beads holds the work; OpenKnowledge holds the knowledge.

## Why this is not a prompt

Setup is not a linear checklist. Clones arrive in different states. The
replacement for "paste this prompt into a new agent" is:

1. Observe (`./scripts/bootstrap.sh` prints the observation block).
2. Apply the matching row in `docs/RESOLVERS.md`.
3. Pour `bootstrap-beads` if setup work still needs a graph.
4. After that, `bd ready` is the prompt.

## Non-negotiables

- Use `bd` for all task tracking. No markdown TODOs or host todo tools as the system of record.
- Create or claim a bead **before** writing code. The pre-commit hook rejects work commits without an in-progress bead (`BD_ISSUE=<id>` or `HUM_SKIP_CLAIM=1` for docs-only).
- Never claim a bead whose type is `gate` or `molecule`. Filter them out.
- Never use `bd edit` (opens `$EDITOR`). Use `bd update` flags or `--description=-`.
- `bd dep add <this> <that>` means **this depends on that**.
- Persist operational insights with `bd remember`; spec and research findings go into OpenKnowledge.
- Spec changes follow `spec/08`: **live assertion → tested digest → normative prose**. Pour `spec-change`; never edit `spec/` prose first.
- Never print `HUMALIKE_API_KEY`, WSS grants, or account identities into beads, logs, or tracked files. `.env` stays untracked.
- Production conformance runs cost credits; state the budget on the bead first. Exit code 3 is "blocked on budget", not "failed".
- Do not commit `bin/bd` (platform-specific). Rebuild with `make bd`.
- Do not `git push` unless the user asked and `origin` exists.
- Prefer non-interactive flags (`cp -f`, `rm -f`, `BD_NON_INTERACTIVE=1`).

## Starting work

| Situation | Move |
| --- | --- |
| Ready real issue | `bd update <id> --claim` |
| Ready is a human gate | wait / `bd gate resolve` — do not claim |
| Nothing ready | `bd blocked` then file or unblock; do not freelance |
| Found extra work | `bd create … --deps discovered-from:<id>` |
| Repeatable multi-step | pour a formula from `.beads/formulas/` |
| One-shot patrol | `bd mol wisp patrol` and drive it with `--mol` |

Full tables: issue types, artifacts (formula/molecule/wisp/gate/todo),
formula authoring, upgrades, host mechanisms — `docs/RESOLVERS.md`.

## Formulas in this repo

| Formula | Pour when |
| --- | --- |
| `bootstrap-beads` | making beads work in a checkout |
| `phase` | delivering one `spec/07` phase (scope → build → conformance → human exit gate) |
| `endpoint` | bringing one HTTP/WSS endpoint to live parity (contract → implement → verify → parity) |
| `conformance` | running both live suites against a target by the `spec/08` rules |
| `spec-change` | a production discovery that must enter the spec (assertion → digest → prose → review) |
| `open-question` | resolving one `spec/08` open question (probe → classify → record) |
| `feature` | new capability |
| `bug` | something broken, incl. a failed live assertion |
| `story` | user-visible slice |
| `spike` | timeboxed unknown |
| `decision` | ADR |
| `chore` | tooling / deps / hygiene |
| `release` | release candidate: notes → conformance → internal gates → tag → human publish |
| `patrol` | ephemeral health loop (wisp this) |

```bash
bd formula list
bd formula show phase --json
bd mol pour endpoint --var method=GET --var path=/v1/whoami --var section=spec/03-api-realtime-memory.md --dry-run
```

Issue types: built-ins plus `conformance` and `question` (`bd types`).

## Session close

1. `bd close` finished work; `bd create` leftovers.
2. `bd remember` anything the next session will need.
3. `make doctor` if you touched formulas or hooks.
4. Report `git status`. Commit only if asked. Never push unprompted.
