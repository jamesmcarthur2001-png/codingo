# midnight-workflow

A Claude Code workflow for the midnight-api monorepo (evermore = CRUD on Postgres/SQLModel, twilight = reverse proxy, midnight_models = shared models, Vue/Vuetify frontend). It's built for a local 27B model: the phase order lives in `state.md` and a Stop hook, checks are scripts, one orchestrator session does the work, and subagents are used only to explore and for two of the reviewers. It installs at user level into `~/.claude` on Ubuntu. The design is in [PROPOSAL.md](PROPOSAL.md).

```
/feature BTRC-1234 "add CSV export to entities" [base] [--no-worktree]

Before you approve (you answer questions)
  1 Setup        branch BTRC-1234-<desc>, base → worktree.py: git worktree at .claude/worktrees/<branch>
                 (or, with --no-worktree, the main checkout switched to the branch) → docs/features/BTRC-1234/state.md
  2 Explore      3 explorers in parallel, same full scope → explore/explorer-<n>.md
                 merged into context.md + patterns.md, items marked 3/3 · 2/3 · 1/3
  3 Grill        every question quotes your words first (grill-notes.md); when the frontend is touched:
                 Playwright reviewer? video? HTML preview? how to run the app? → state.md ## Frontend
                 HTML preview → docs/features/BTRC-1234/mockups/<screen>.html, changed until you approve
  4 Spec + plan  spec.md (links the mockups), plan.md (2–4 slices, each with its allowed Files)
  5 ★ You approve: the last question

After (no questions; the Stop hook keeps it going until DONE or BLOCKED)
  6 Build        per slice → check_slice.py (lint, types, suppressions, scope; changed lines only)
  7 Tests        test-plan.md (4 columns) → tests → changed-line coverage
  8 Gate A       gate_a.py: project lint/typecheck/test, 100% changed-line coverage or a reason, scope, no suppressions
  9 Gate B       one parallel review round: run_beatrice.py (Beatrice ×2, read-only, merged 2/2 · 1/2)
                 + conventions-reviewer (changed lines only) + playwright-reviewer (when chosen; app in a real browser)
                 → review_round.py capture → one triage.md with a Source column → fix → Gate A … ≤ 5 rounds
 10 Video        (when chosen) one Playwright recordVideo run of the new behaviour → video/BTRC-1234.webm; never blocks
 11 Finish       finish_branch.py: commit, pull --rebase, push with a lease, pipeline, containers down, worktree removed, base pulled
 12 summary.md
```

Dropped connection? `claude --continue`, then `/feature resume BTRC-1234`. Every step writes `state.md` first, so nothing is lost.

---

## Install (Ubuntu, user level)

Requirements: `python3` ≥ 3.10, `git`, and in the monorepo `uv` (with `ruff`, `mypy`, `pytest-cov`, `diff-cover` as dev dependencies of each Python service), the frontend's `eslint` in `node_modules`, `glab` logged in, and `docker compose`.

```bash
./install.sh
```

It copies, and records what it copied in `~/.claude/midnight-workflow/installed-files.txt`:

| From the repo | To |
|---|---|
| `commands/feature.md`, `map-services.md`, `map-library.md` | `~/.claude/commands/` (`/feature`, `/map-services`, `/map-library`) |
| `agents/explorer.md`, `conventions-reviewer.md`, `playwright-reviewer.md`, `doc-auditor.md`, `skill-mapper.md` | `~/.claude/agents/` |
| `skills/*` | `~/.claude/skills/` |
| `scripts/**/*.py` | `~/.claude/midnight-workflow/scripts/` (executable) |
| `settings/hooks.json` | merged into the `hooks` of `~/.claude/settings.json` |

The settings merge backs up `settings.json` first (`settings.json.bak-<time>`), keeps every other key and hook, and replaces its own earlier entries, so running `install.sh` again updates without duplicates. A file it would overwrite that it didn't install (e.g. your own `~/.claude/skills/python-conventions`) is backed up under `~/.claude/midnight-workflow/backup/`.

```bash
./uninstall.sh
```

removes exactly the recorded files and the workflow's hook entries, and puts the backed-up files back.

Then:
1. Copy the CLAUDE.md drafts from `claude-md/` into midnight-api (see `claude-md/README.md`).
2. Generate the service map once from the monorepo root: `/map-services`.
3. Each feature's `state.md` names the Beatrice command file (`Beatrice command: ~/.claude/commands/beatrice-code-review.md` or the repo's `.claude/commands/`). The file itself is never changed.

`agents/review-*.md` from the old flow are kept in `unused/agents/` and are not installed.

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

All four are user-level, so they run in every repository. Each exits 0 at once when `MIDNIGHT_ROLE=reviewer`.

| Hook | When | What |
|---|---|---|
| `post_edit_checks.py` | After every Write/Edit | Only while an approved, unfinished feature is active for that repo (or with `MIDNIGHT_CHECKS=1`), and only for files in its code root (the worktree, or the main checkout with `--no-worktree`). Runs the convention checker + `ruff` (`.py`/`.pyi`) or `eslint` (`.vue`/`.ts`/`.js`/…), and the suppression check (code and tool configs). Reports **only problems touching changed lines**: `git diff -U0 <merge-base with the base> -- <file>`; the whole file when it's untracked. `get_` names that existed in the base version aren't reported. |
| `guard_test_plan.py` | Before Write/Edit of a test file | Only for an approved, unfinished feature: blocks a new test whose exact name isn't in the first column of `test-plan.md`. |
| `guard_branch.py` | Before every Bash command, everywhere | On `checkout -b/-B/--orphan`, `switch -c/-C/--create[=]`, `branch <name>`, `branch -m`, `worktree add [-b]` (also without `-b`, where the branch is the folder name), `push <remote> <src>:<name>` (not deletes) — also inside `bash -c "…"`, after `VAR=…`/`sudo`/`env`, in `( … )` or after `&` — it fetches (15 s, no prompts) and blocks if another local or remote branch has the same `BTRC-<n>`. If the fetch fails it still checks and says the remote refs may be stale. |
| `next_step.py` | Stop | After approval, refuses to stop until `state.md` says `DONE` or `BLOCKED`, and returns the next step for the current `Phase`. It records the orchestrator's `session_id` as `Session:` on the first stop and ignores other sessions. Never blocks before approval or while a long script runs (`.running.json`). Circuit breaker: after 8 blocks without `state.md` changing it writes `BLOCKED: no progress`; the counter resets whenever a stop is allowed. |

### Environment variables

- `MIDNIGHT_ROLE=reviewer`: set by `run_beatrice.py` for the two `claude -p` Beatrice sessions, so the reviewers aren't blocked, checked or kept running by the orchestrator's hooks. Don't set it in your own sessions.
- `MIDNIGHT_CHECKS=1`: run the post-edit checks outside a feature too (e.g. while you edit by hand).

## The workflow scripts

Run from the repository root (the folder that holds `docs/features/`) as `python3 "$HOME/.claude/midnight-workflow/scripts/<name>.py"`. All read the branch, base, worktree, compose project/files and Beatrice command from `docs/features/<ticket>/state.md`. The long ones (`gate_a`, `run_beatrice`, `finish_branch`) hold `.running.json` for their whole run; a second run of the same feature refuses to start (exit 2).

| Script | Does | Exit codes |
|---|---|---|
| `worktree.py create <T> [--no-worktree]` · `remove <T>` | `create` fetches the base and runs `git worktree add -b <Branch> .claude/worktrees/<Branch> origin/<Base>`, or `git worktree add .claude/worktrees/<Branch> <Branch>` when the branch exists (locally or on origin); it never creates a second branch for the same BTRC-n. With `--no-worktree` it switches the main checkout to the branch (creating or reusing it). It keeps `.claude/worktrees/` and `docs/features/` in `.git/info/exclude` and records `Worktree:` / `Worktree mode:`; if the worktree already exists it only records it. `remove` removes the worktree (the branch stays); `finish_branch.py` uses the same logic. Its git calls don't pass through the Bash hook. | 0 · 1 git failed · 2 setup (incl. another branch for the ticket) |
| `check_slice.py <T> <n>` | Changed-line checks (conventions, ruff, eslint, `mypy --strict`, suppressions) + scope (changed, deleted or renamed files outside slices 1..n fail; changed existing lines are listed). Advances `Slice`/`Phase` on pass. | 0 pass · 1 problems · 2 setup (incl. git errors, unknown base) |
| `gate_a.py <T>` | Same checks over the branch (scope = all slices + test-plan files), then every `## Commands` entry through `bash -lc`; `coverage*` entries must use `diff-cover --include-untracked`, are read as diff-cover output, minus `## Coverage exemptions` (exact repo-relative paths). Fails if diff-cover saw no lines while code changed. Syncs dismissed findings per source from `review/triage.md` (Source column: beatrice, conventions, playwright). Sets `Phase: GATE-B`, or `VIDEO`/`FINISH` once round 5 is triaged. | 0 · 1 · 2 |
| `run_beatrice.py <T> <round>` | Two read-only `claude -p --output-format json` sessions in parallel in the worktree (`--disallowedTools Edit,Write,MultiEdit,NotebookEdit`, `--permission-mode default`, a narrow `--allowedTools`), 30 min timeout, one retry each; a slash command that doesn't run is retried with the command file's text. Asks for a machine-readable findings block through `--append-system-prompt` (the command file stays unchanged) and falls back to reading free-form output. Merges into `review/beatrice-<round>.md` (`2/2`/`1/2`, earlier dismissals noted) and `beatrice-<round>.json` (with each flagged line's text, which the dismissed-findings memory uses). Round 1 goes into `beatrice-log.md` once. | 0 · 1 both runs failed · 2 |
| `review_round.py capture <T> <round>` · `playwright-needed <T> <round>` | `capture` (run when the round's reviewers have finished, before fixing) reads `review/conventions-<round>.md` and `review/playwright-<round>.md` (findings as `## C<round>-<i> \| <file:line> \| <rule>` / `## P…`), stores them with each flagged line's text in `<source>-<round>.json`, notes findings dismissed in earlier rounds, and records a fingerprint of the changed frontend files. `playwright-needed` prints `yes` in round 1 and later only when frontend files changed since the reviewer's last run (and only when the grill chose the reviewer). | 0 · 2 |
| `finish_branch.py <T>` | Checks the code root (worktree, or the main checkout when `Worktree mode: none`) is on `Branch` and `Branch` ≠ `Base`; commit (or, after a conflict, refuses while files are unmerged or hold `<<<<<<<`/`>>>>>>>`, then `rebase --continue`) → fetch → refuses if the remote branch moved to a commit this script didn't push → pull --rebase → push `HEAD:refs/heads/<Branch>` with `--force-with-lease=<ref>:<last pushed commit>` → `glab ci status` every 30 s (≤ 45 min) → `docker compose -p <project> -f <files> down --remove-orphans` → the worktree is removed (skipped without a worktree) → pull the base in the main checkout. Finished steps are recorded under `## Finish`, so a re-run resumes. | 0 · 10 conflict · 20 pipeline failed · 30 push rejected · 1 other · 2 setup |

Each script counts failed runs in `Tries:`; the third failed run of the same step (or the same finish code) writes `BLOCKED`. Exit 30 blocks at once.

Outside the workflow you can still run:
```bash
python3 "$HOME/.claude/midnight-workflow/scripts/check_python_conventions.py" app/
```
```bash
python3 "$HOME/.claude/midnight-workflow/scripts/mypy_strict.py" app/
```

## Not verified offline

These need checking in the work environment; each has an isolated spot to adjust.

| Point | Where to adjust |
|---|---|
| `claude -p "/beatrice-code-review <base>"` runs a custom slash command. If not, the script retries with the command file's text by itself; set `Beatrice mode: file` to start that way. | `run_beatrice.py` `build_prompt`, `run_review` |
| `--allowedTools` / `--disallowedTools` syntax (one comma-separated argument each), `--append-system-prompt`, the `--output-format json` fields (`is_error`, `result`, `permission_denials`), and which Bash commands Beatrice really runs. Override the allowed list per feature with `Beatrice tools:`. | `run_beatrice.py` `DEFAULT_ALLOWED_TOOLS`, `read_review_result` |
| Beatrice's output format. The findings block is asked for; without it the free-form parser reads bullets, numbered items, tables (by header) and numbered/located headings, and the raw outputs are always kept. | `run_beatrice.py` `parse_free_form` |
| `glab ci status --branch <b>` flags and output (`Pipeline state:`, `SHA:`, tab-separated `(failed)` job lines), and `glab ci trace <job> --branch <b>`. `glab ci get -b <b> -F json` may be the sturdier source. | `finish_branch.py` `parse_pipeline_state`, `failed_job_name` |
| `$HOME` is expanded in the hook commands (they run through a shell). | `settings/hooks.json` |
| The Playwright reviewer and the video: no frontend repo or Playwright on this machine. The agent loads Playwright from the frontend folder with `require(require.resolve('playwright', { paths: [...] }))` from a script in `docs/features/<T>/playwright/`, uses only preinstalled browsers, and mocks the API with `page.route()` or uses the branch's docker stack. `recordVideo` output naming, the dev-server start/stop and the login flow need a real run. | `agents/playwright-reviewer.md`, `commands/feature.md` step V |
| The HTML mockups use CSS `:has()` for the theme/RTL/state switches (no JavaScript); the offline browser must support it (Chromium 105+, Firefox 121+). | `skills/html-mockups/templates/mockup.html` |
| `.claude/rules/*.md` with a `paths:` glob, as an alternative to folder CLAUDE.md files. | `claude-md/README.md` |
| The midnight-api paths in `claude-md/`, the `## Commands` lines, `Compose files`, and the Beatrice command path. | each feature's `state.md` |
| Add `-v` to `docker compose down` only if the branch's volumes hold nothing you need. | `finish_branch.py` `stop_containers` |

## Developing

```bash
uv run --with pytest pytest tests -q
```

The tests mock `glab`, `docker` and `claude` at `command_runner.run_command`; git runs for real (temporary repositories, a bare remote and a worktree for the finish tests). The install tests and the process-group tests run only on Linux.
