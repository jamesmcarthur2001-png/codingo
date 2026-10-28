# midnight-workflow

A Claude Code workflow for the midnight-api monorepo (evermore = CRUD on Postgres/SQLModel, twilight = reverse proxy, midnight_models = shared models, Vue/Vuetify frontend). It's built for a local 27B model: the phase order lives in `state.md` and a Stop hook, checks are scripts, one orchestrator session does the work, and subagents are used only to explore. The design is in [PROPOSAL.md](PROPOSAL.md) (draft v5).

```
/midnight-workflow:feature BTRC-1234 "add CSV export to entities" [base]

Before you approve (you answer questions)
  1 Setup        branch BTRC-1234-<desc>, base, worktree → docs/features/BTRC-1234/state.md
  2 Explore      3 explorers in parallel, same full scope → explore/explorer-<n>.md
                 merged into context.md + patterns.md, items marked 3/3 · 2/3 · 1/3
  3 Grill        questions quote your words first (grill-notes.md)
  4 Spec + plan  spec.md, plan.md (2–4 slices, each with its allowed Files)
  5 ★ You approve: the last question

After (no questions; the Stop hook keeps it going until DONE or BLOCKED)
  6 Build        per slice → check_slice.py (lint, types, suppressions, scope; changed lines only)
  7 Tests        test-plan.md (4 columns) → tests → changed-line coverage
  8 Gate A       gate_a.py: project lint/typecheck/test, 100% changed-line coverage or a reason, scope, no suppressions
  9 Gate B       run_beatrice.py: Beatrice ×2 in parallel, merged 2/2 · 1/2 → triage → fix → Gate A … ≤ 5 rounds
 10 Finish       finish_branch.py: commit, pull --rebase, push --force-with-lease, pipeline, containers down, worktree removed
 11 summary.md
```

Dropped connection? `claude --continue`, then `/midnight-workflow:feature resume BTRC-1234`. Every step writes `state.md` first, so nothing is lost.

---

## Contents

| Path | What |
|---|---|
| `commands/feature.md` | The orchestrator (`/midnight-workflow:feature`) |
| `commands/map-services.md`, `commands/map-library.md` | Generate the `service-map` skill; audit a library's docs (standalone) |
| `agents/explorer.md` | Explores the whole feature scope; 3 run in parallel |
| `agents/doc-auditor.md`, `agents/skill-mapper.md` | Used only by `map-library` |
| `agents/review-*.md` | The old reviewers. Kept, not used by `/feature` (Beatrice replaces them) |
| `skills/*-conventions`, `sql-conventions` | Conventions, each with short checklists the orchestrator loads per slice |
| `skills/grill-with-docs`, `write-spec`, `test-plan` | Workflow phases (with templates) |
| `skills/backend-test-infra`, `vitest-conventions`, `browser-test-conventions` | Test setup per layer |
| `hooks/hooks.json` | The four hooks below |
| `scripts/` | Hook scripts, workflow scripts, the convention checker, the mypy wrapper |
| `claude-md/` | Drafts of the six midnight-api CLAUDE.md files, at their target paths (see its README) |
| `tests/` | pytest tests for every script and hook |

## Install

1. **Requirements:** `python` 3.10+ on PATH (hooks and scripts), `git`. In the monorepo: `uv`, and as dev dependencies of each Python service `ruff`, `mypy`, `pytest-cov`, `diff-cover`; the frontend's `eslint` in `node_modules`; `glab` (logged in) for the pipeline step; `docker compose` for the containers step.
2. **Add the plugin:**
   ```
   /plugin marketplace add C:\path\to\claude-workflow
   /plugin install midnight-workflow@midnight-workflow
   ```
   To try it without installing: `claude --plugin-dir C:\path\to\claude-workflow`.
3. **Copy the CLAUDE.md drafts** from `claude-md/` into midnight-api (see `claude-md/README.md`).
4. **Generate the service map** once from the monorepo root: `/midnight-workflow:map-services`.
5. **Point the workflow at Beatrice.** Setup writes `Beatrice command: <path to beatrice-code-review.md>` into each feature's `state.md`; the command file itself is never changed.

## Model settings (LiteLLM)

The orchestrator and the explorers use the session's model. Point Claude Code at LiteLLM in `~/.claude/settings.json` (model names are placeholders):

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://<your-litellm-host>",
    "ANTHROPIC_AUTH_TOKEN": "<your LiteLLM key>",
    "ANTHROPIC_MODEL": "qwen3.8-27b",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "qwen3.8-27b",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "qwen3.8-27b",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "qwen3.8-27b"
  }
}
```

If long answers get cut off with "connection closed mid-response", try a lower `CLAUDE_CODE_MAX_OUTPUT_TOKENS` and a higher `API_TIMEOUT_MS` in the same `env` block (the cause in your setup is unverified).

## The hooks

| Hook | When | What |
|---|---|---|
| `post_edit_checks.py` | After every Write/Edit | Runs the convention checker + `ruff` (`.py`) or `eslint` (`.vue`/`.ts`), and the suppression check. Reports **only problems on changed lines**: `git diff -U0 <merge-base with the base> -- <file>`; the whole file when it's new/untracked. The base is the active feature's `Base:`, else `origin/HEAD`, else master/main. |
| `guard_test_plan.py` | Before Write/Edit of a test file | While a feature is active, blocks a new test whose name isn't in `test-plan.md`. |
| `guard_branch.py` | Before every Bash command | On `checkout -b/-B`, `switch -c/-C`, `branch <name>`, `branch -m`, `worktree add -b`, `push <remote> <x>:<name>`: runs `git fetch --prune` and blocks if another branch (local or remote) has the same `BTRC-<n>`. No exceptions; create a second one yourself if you really need it. |
| `next_step.py` | Stop | After approval, refuses to stop until `state.md` says `DONE` or `BLOCKED`, and returns the next step for the current `Phase`. Never blocks before approval. Lets the orchestrator wait while a long script runs (`.running.json`). Circuit breaker: after 8 blocks without `state.md` changing it writes `BLOCKED: no progress` and lets it stop. |

### `MIDNIGHT_ROLE`

Every workflow hook exits 0 at once when the environment variable `MIDNIGHT_ROLE=reviewer` is set. `run_beatrice.py` sets it for the two `claude -p` Beatrice sessions, so the reviewers aren't blocked, checked or kept running by the orchestrator's hooks. Don't set it in your own sessions.

## The workflow scripts

Run from the repository root (the folder that holds `docs/features/`). All read the branch, base, worktree, compose project and Beatrice command from `docs/features/<ticket>/state.md`.

| Script | Does | Exit codes |
|---|---|---|
| `check_slice.py <T> <n>` | Changed-line checks (conventions, ruff, eslint, `mypy --strict`, suppressions) + scope (files outside slices 1..n fail; changed existing lines are listed). Advances `Slice`/`Phase` on pass. | 0 pass · 1 problems · 2 setup |
| `gate_a.py <T>` | Same checks over the whole branch (scope = all slices + test-plan files), then every `## Commands` entry; `coverage*` entries are read as diff-cover output and `## Coverage exemptions` are subtracted. Syncs dismissed findings from `review/triage.md` (`--dismissed` prints them). Sets `Phase: GATE-B` on pass. | 0 · 1 · 2 |
| `run_beatrice.py <T> <round>` | Two `claude -p` sessions in parallel in the worktree, 30 min timeout, one retry each; merges into `review/beatrice-<round>.md` with `2/2`/`1/2` marks and "dismissed in round N, because …" notes. Round 1 is appended to `beatrice-log.md`. | 0 · 1 both runs failed · 2 |
| `finish_branch.py <T>` | commit → fetch → pull --rebase → push --force-with-lease → `glab ci status` every 30 s (≤ 45 min) → `docker compose -p <project> down` → `git worktree remove`. Each step checks if it's still needed, so a re-run resumes. | 0 done · 10 conflict · 20 pipeline failed · 30 push rejected · 1 other |

Each script counts failed runs in `Tries:`; the third failed run of the same step (or the same finish code) writes `BLOCKED`. Exit 30 blocks at once.

Outside the workflow you can still run:
```bash
python scripts/check_python_conventions.py <files or dirs>
```
```bash
python scripts/mypy_strict.py <paths>
```

## Not verified on this machine

These need checking in the offline work environment; each has an isolated spot to adjust.

| Point | Where to adjust |
|---|---|
| `claude -p "/beatrice-code-review <base>"` runs a custom slash command. If it doesn't, set `Beatrice mode: file` in `state.md`: the script then sends the command file's text (frontmatter removed, `$ARGUMENTS` = base) as the prompt. | `run_beatrice.py` `build_prompt` |
| `--allowedTools "Read,Grep,Glob,Agent,Bash(git diff:*),…"` syntax (one comma-separated argument), and which Bash commands Beatrice really runs. Override per feature with `Beatrice tools:` in `state.md`. | `run_beatrice.py` `DEFAULT_ALLOWED_TOOLS` |
| Beatrice's output format. Findings are read tolerantly (bullets, numbered items, table rows; `file:line`, `PY-12`-style IDs or `rule: x`); the raw outputs are always kept next to the merged file. | `run_beatrice.py` `parse_findings` |
| `glab ci status --branch <b>` flags and output (`Pipeline state:`, `SHA:`, `(failed) … <job>` lines), and `glab ci trace <job> --branch <b>`. | `finish_branch.py` `parse_pipeline_state`, `failing_job_log` |
| `${CLAUDE_PLUGIN_ROOT}` is expanded inside `commands/feature.md` (it is in hooks.json). If it isn't, the Stop hook's messages still give the absolute script paths. | `commands/feature.md` |
| `.claude/rules/*.md` with a `paths:` glob, as an alternative to folder CLAUDE.md files. | `claude-md/README.md` |
| The midnight-api paths in `claude-md/`, the `## Commands` lines (e.g. `npx nx affected -t lint --base=origin/<base>`), and the Beatrice command file path. | each feature's `state.md` |
| Add `-v` to `docker compose down` only if the branch's volumes hold nothing you need. | `finish_branch.py` `stop_containers` |

## Developing the plugin

```bash
uv run --with pytest pytest tests
```
```bash
claude plugin validate .
```
