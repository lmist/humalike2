# Resolvers

Agents in this repo do not follow a linear setup prompt. A clone may already
have `vendor/beads`, or a stale Homebrew `bd`, or a half-init `.beads/`.
**Observe, then look up the row.** Apply only that row.

What we are building: the Humalike API recreation specified in `spec/`
(`spec/00-index.md` is the normative index; `spec/07-implementation-plan.md`
lists phases 0–8; `spec/08-parity-and-open-questions.md` defines the live
conformance gate and the discovery discipline). `spec/`, `research/` and
`sources/` are OpenKnowledge-governed markdown: read and edit them through the
`open-knowledge` MCP tools (`exec("cat spec/…")`, `edit`, `write`), never with
native file tools. Beads tracks the *work*; OpenKnowledge holds the *knowledge*.

Always invoke beads as:

```bash
export PATH="$PWD/bin:$PATH"    # or: ./scripts/bd <cmd>
bd <cmd> --json                 # machines
```

`./bin/bd` is built from `vendor/beads` (gastownhall/beads **v1.2.2**). Never
use `/opt/homebrew/bin/bd` or `~/.local/bin/bd` in this repo.

---

## 0. Session start

| You observe | Do this |
| --- | --- |
| No `vendor/beads/cmd/bd/main.go` | `./scripts/bootstrap.sh` |
| No executable `bin/bd` | `make bd` |
| `command -v bd` is not `<repo>/bin/bd` | `export PATH="$PWD/bin:$PATH"`; ignore the "multiple binaries" warning |
| `bin/bd` exists, no `.beads/metadata.json` | `BD_NON_INTERACTIVE=1 ./bin/bd init --non-interactive --role maintainer -p hum --skip-agents` |
| `.beads/` exists but `bd info` fails | `./bin/bd bootstrap --yes` (never `bd init --force`) |
| `bd types` lacks `conformance` / `question` | `make types` |
| Formulas missing / `bd formula list` empty | restore `.beads/formulas/` from git; `./scripts/check-formulas.sh` |
| Hooks lack `BEGIN HUM PATH` markers | `make hooks` |
| Database healthy | `bd prime` then `bd ready` — do **not** re-init |

Chicken-and-egg: you cannot pour a bead until `bin/bd` exists. That is the
only job of `scripts/bootstrap.sh`. After it succeeds, work lives in beads.

To (re)materialize the setup graph itself:

```bash
bd mol pour bootstrap-beads --var prefix=hum
bd ready --mol <id>
```

If an open issue already has label `bootstrap`, do not pour a second copy.

### Agent hosts

Each host has a committed mechanism that puts `<repo>/bin` first on PATH.
If `command -v bd` still resolves elsewhere, the mechanism is not active —
fall back to the explicit `export` above.

| Host | Mechanism | Verify |
| --- | --- | --- |
| Claude Code | `.claude/settings.json` `SessionStart` → `scripts/agent-env.sh` appends `export PATH=…` to `$CLAUDE_ENV_FILE` (runs as a preamble before every Bash call) | `command -v bd` |
| Codex CLI | `.codex/hooks.json` `PreToolUse` (matcher `^Bash$`) → `scripts/agent-path-rewrite.sh codex` rewrites each command with the PATH prefix. Loads only when the project is **trusted** and the hook is trusted once via `/hooks` | `command -v bd` |
| Cursor | `.cursor/hooks.json` `preToolUse` (matcher `Shell`) → `scripts/agent-path-rewrite.sh cursor`; `.cursor/rules/beads.mdc` always-applied rule as the soft fallback | `command -v bd` |
| Plain terminal | `.envrc` (`PATH_add bin`, needs `direnv allow`) or the `export` | `command -v bd` |

Git hooks are independent of the host: `.beads/hooks/*` carry a `HUM PATH`
block outside the beads markers, so `bd` inside hooks is always `./bin/bd`.

---

## 1. What kind of work is this?

Pick the **artifact** first (how it lives), then the **issue type** (what it is).

### Project shapes (pour these for spec work)

| You have | Formula | Pour |
| --- | --- | --- |
| A whole `spec/07` phase to deliver | `phase` | `bd mol pour phase --var number=2 --var name="Thread state and realtime delivery"` |
| One HTTP/WSS endpoint to bring to parity | `endpoint` | `bd mol pour endpoint --var method=POST --var path=/v1/threads --var section=spec/03-api-realtime-memory.md` |
| Need the live suites run against a target | `conformance` | `bd mol pour conformance --var target=http://localhost:8080 --var reason="phase 2 exit"` |
| Production behaved differently from the spec | `spec-change` | `bd mol pour spec-change --var finding="…"` — assertion → digest → prose, **never prose first** |
| One of the `spec/08` open questions | `open-question` | `bd mol pour open-question --var question="5. Authorization and throttling"` |

Conformance rules that every step obeys (`spec/08`): exit code `0` green,
`1` assertion failures, `3` credit-depleted (**budget blocker, never a
regression**); green means zero failures *and* zero skips; production runs
cost credits (realtime ≈52, intelligence ≈800–880) and need an approved
budget; never print keys, grants, or account identities into beads or logs.

### Artifact resolver (workflows)

| You have | Artifact | Command | Do not |
| --- | --- | --- | --- |
| A one-line thought you must not lose | **todo** (task bead) | `bd todo add "…"` | markdown TODOs, host todo tools as the system of record |
| A bug found while doing something else | **bug** + `discovered-from` | `bd create -t bug --deps discovered-from:<current>` | bury it in the current bead's notes |
| A user-facing slice of value | **story** | pour `story` | inflate it into an epic on day one |
| New capability, multi-step, will recur | **formula** → **molecule** | write `.beads/formulas/X.formula.toml`, then `bd mol pour X` | re-plan the DAG by hand every time |
| Same shape, no audit value (patrol, health) | **wisp** | `bd mol wisp patrol` or `bd create --ephemeral` | expect it on plain `bd ready` — wisps are hidden there |
| Anything we must explain later | **pour** (persistent molecule) | `bd mol pour X` | wisp it |
| Large body with children | **epic** / molecule root | `bd create -t epic` or pour `phase` | put all the work on the epic itself |
| Timeboxed unknown | **spike** | pour `spike` | open an unbounded research epic |
| "Should we do X this way?" | **decision** | pour `decision` | a chat thread |
| Maintenance, deps, tooling | **chore** | pour `chore` or `bd create -t chore` | disguise it as a feature |
| Something broken | **bug** | pour `bug` | a task named "fix …" |
| New functionality | **feature** | pour `feature` | a pile of untitled tasks |
| Named completion line, no work of its own | **milestone** | `bd create -t milestone` | stuff implementation into it |
| Waiting on a **person** | **human gate** | `[steps.gate] type = "human"` or `bd gate create --type=human --blocks <id>` | a fake "wait" task an agent will claim |
| Waiting on a **clock** | **timer gate** | `[steps.gate] type = "timer"` `timeout = "30m"` (literal, no `d` unit) | `timeout = "{{var}}"` — it becomes zero |
| Waiting on **CI / PR** | **gh:run / gh:pr gate** | `[steps.gate] type = "gh:run"` | poll in a loop |
| Waiting on **another bead** | **bead gate** | `[steps.gate] type = "bead"` | a `needs` edge to work outside this graph |
| Waiting on **another step in this graph** | **needs** | `needs = ["design"]` | a gate |

### Issue type resolver (`bd types`)

| Type | Use when | Default priority | Formula |
| --- | --- | --- | --- |
| `bug` | Broken behavior, failed live assertion | 1 | `bug` |
| `feature` | New capability / endpoint implementation | 2 | `feature`, `endpoint` |
| `task` | Tests, docs, refactor, glue, formula steps | 2 | (todo, or a step inside a molecule) |
| `chore` | Tooling, deps, repo hygiene | 3 | `chore` |
| `epic` | Span of children, no single diff | 2 | root of `phase` |
| `story` | User-visible slice | 2 | `story` |
| `spike` | Timeboxed investigation | 2 | `spike` |
| `decision` | ADR that other work should cite | 2 | `decision` |
| `milestone` | A finish line, contains no work | 2 | — |
| `conformance` *(custom)* | A live-suite run record against a target | 1 | `conformance` |
| `question` *(custom)* | A `spec/08` open question being resolved | 2 | `open-question` |

Custom types are registered by `make types` (`bd config set types.custom`).
Formula **steps** must use built-in types only — unknown step types silently
become `task`.

Priority: `0` critical, `1` high, `2` medium, `3` low, `4` backlog.

### Persistence resolver

| Need | Use |
| --- | --- |
| Survives clones, PRs, blame | `bd mol pour` / normal beads |
| Throwaway operational loop | `bd mol wisp` / `--ephemeral` |
| Template others will instantiate | formula file in `.beads/formulas/` |
| Session scratch | nothing — if it matters, it is a bead |
| Knowledge (findings, sources, spec text) | OpenKnowledge docs, via MCP — not beads notes |

---

## 2. How to start work

| You observe | Do this |
| --- | --- |
| `bd ready` shows a real step (not `gate` / `molecule`) | `bd update <id> --claim` |
| Ready list is a gate titled `Gate: human` | **do not claim it** — `bd human` / wait for `bd gate resolve` |
| Ready list is a timer/gh gate | `bd gate check` then re-read ready |
| Only wisps exist and `bd ready` is empty | `bd todo` or `bd ready --mol <wisp-root>` |
| Nothing ready, things blocked | `bd blocked` — file a bead or resolve a gate; do not invent parallel work |
| You discovered extra work | `bd create … --deps discovered-from:<current>` then keep going |
| Two beads are the same | `bd duplicate <loser> <winner>` |

Claim is required before a non-trivial commit. The extra pre-commit hook
enforces this. Bypass with `HUM_SKIP_CLAIM=1` or `BD_ISSUE=<id>`. Commits to
`.beads/`, `.gitignore`, `.okignore`, `spec/`, `research/`, `sources/` alone
do not need a claim. `prepare-commit-msg` prefixes the subject with the bead
id when `BD_ISSUE` is set or exactly one bead is in progress.

### Molecule ready filter

`bd ready --mol <id>` lists the **root** and **gates** as ready. Filter:

```bash
bd ready --mol <id> --json | python3 -c "
import sys, json
d = json.load(sys.stdin)
skip = {'gate', 'molecule'}
items = d.get('steps') or d.get('issues') or d
if isinstance(items, dict):
    items = items.get('issues') or items.get('steps') or []
for s in items:
    i = s.get('issue', s)
    t = i.get('issue_type') or i.get('type')
    if t in skip: continue
    print(i.get('priority'), i.get('id'), i.get('title'))
"
```

---

## 3. Formula authoring (when you add a workflow)

Mandatory loop — unknown TOML keys are dropped in silence:

```bash
bd formula show <name> --json     # what the parser kept
bd mol pour <name> --dry-run      # what would actually be created
./scripts/check-formulas.sh
```

| Rule | Why |
| --- | --- |
| `formula` + `version >= 1` required | validation fails otherwise |
| Step `type` is `task\|bug\|feature\|epic\|chore` | anything else becomes `task` silently (`human` is not a type) |
| Human waits are `[steps.gate]` on the **previous** `[[steps]]` | `[steps.foo.gate]` is ignored |
| `needs = ["earlier"]` means this step **requires** earlier | `bd dep add <this> <that>` — dependent first |
| `{{var}}` substitutes in title/description/notes/assignee/gate `await_id` | **not** in `labels` or gate `timeout` |
| Loop vars use `{n}` (single braces) | not `{{n}}` |
| `condition` is evaluated at pour, not cook | preview with `--dry-run`, not `bd cook` |
| If step B must not run when optional A is skipped | give B the **same** `condition`, do not rely on `needs = ["A"]` |

Search paths: `.beads/formulas/` (this repo), then `~/.beads/formulas/`.
`vendor/beads/.beads/formulas` has no metadata — discovery walks past it.

---

## 4. Session close

This repo is conservative about git: **do not push** unless the user asked
and `origin` exists.

| Step | Command |
| --- | --- |
| File leftovers | `bd create` / `bd todo add` |
| Close finished work | `bd close <id> --reason "…"` |
| Unclaim abandoned | `bd unclaim <id>` |
| Persist an insight | `bd remember "…" --key <slug>` (operational); spec/research findings go to OpenKnowledge |
| Quality | `make doctor` if you touched formulas/hooks |
| Git | report `git status`; commit only if asked |
| Handoff | next ready id + one sentence of context |

Do not use `bd edit`. Use `bd update --description=-` via stdin for messy text.

---

## 5. Upgrade beads

Pinned: **git subtree `vendor/beads` @ tag v1.2.2**.

| You want | Do |
| --- | --- |
| Rebuild current pin | `make bd` |
| Move the pin | `git fetch beads-upstream --tags` then `git subtree pull --prefix=vendor/beads beads-upstream <tag> --squash`, bump `VENDOR_REF` in `Makefile` and `scripts/bootstrap.sh`, then `make bd` |
| After any binary change | `make hooks` (shims mention the version) |

---

## 6. File map

| Path | Role |
| --- | --- |
| `vendor/beads/` | squash-subtree of `gastownhall/beads` @ v1.2.2 |
| `bin/bd` | built binary (gitignored, ~190MB, platform-specific) |
| `scripts/bd` | wrapper that refuses PATH fallback |
| `scripts/bootstrap.sh` | pre-bd resolver |
| `scripts/agent-env.sh` | Claude Code SessionStart hook (PATH + orientation) |
| `scripts/agent-path-rewrite.sh` | Codex / Cursor PreToolUse command rewrite |
| `scripts/install-extra-hooks.sh`, `scripts/hooks/*.sh` | git-hook extras outside the beads markers |
| `scripts/set-types.sh` | registers `conformance`, `question` |
| `scripts/doctor.sh` | `make doctor` — `bd doctor` is unavailable in embedded-Dolt mode, so this checks pin, PATH, hooks, host hooks, formulas, secrets |
| `.beads/formulas/` | the workflows (generic + project shapes) |
| `docs/RESOLVERS.md` | this file |
| `AGENT_INSTRUCTIONS.md` | the contract; `AGENTS.md` / `CLAUDE.md` / `.cursor/rules/beads.mdc` point here |
| `spec/`, `research/`, `sources/`, `tests/` | the product: specification, evidence, sources, live conformance suites |
