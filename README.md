# claude-workflow

A Claude Code workflow for our monorepo (evermore = CRUD on Postgres/SQLModel, twilight = reverse proxy, a shared models library, Vue/Vuetify frontend). It's built for a local 27B model: the phase order lives in `state.md` and a Stop hook, checks are scripts, one orchestrator session does the work, and the orchestrator's own subagents are used only to explore and for the review round (5 reviewers, a verifier each, up to 5 at once). Everything lives plainly under `~/.claude` (Ubuntu, user level). The design is in [PROPOSAL.md](PROPOSAL.md).

```
/feature BTRC-1234 "add CSV export to entities" [base] [--no-worktree]

Before you approve (you answer questions)
  1 Setup        branch BTRC-1234-<desc>, base → worktree.py: git worktree at .claude/worktrees/<branch>
                 (feature folder moves into it) → EnterWorktree; with --no-worktree, the main checkout is switched instead
  2 Explore      3 explorers in parallel, same full scope → explore/explorer-<n>.md
                 merged into context.md + patterns.md, items marked 3/3 · 2/3 · 1/3
  3 Grill        every question quotes your words first (grill-notes.md); when the frontend is touched:
                 Playwright reviewer? video? HTML preview? how to run the app? → state.md ## Frontend
                 HTML preview → docs/features/BTRC-1234/mockups/<screen>.html, changed until you approve
  4 Spec + plan  spec.md (links the mockups), plan.md (2–4 slices, each with its allowed Files)
  5 ★ You approve: the last question

After (no questions; the Stop hook keeps it going until DONE or BLOCKED)
  6 Build        per slice → check_changes.py --slice (lint, types, suppressions, scope; changed lines only)
  7 Tests        test-plan.md (4 columns) → tests → changed-line coverage
  8 CI           check_changes.py, commit, push, watch the glab pipeline (lint, typecheck, tests, coverage) until it passes
  9 Gate B       review round: 5 reviewers at once (correctness, conventions, tests, spec, playwright when chosen),
                 each file ends `Done: k finding(s)` → capture → a finding-verifier per reviewer: sure / unsure / invalid
                 → triage.md (sure = fix, invalid = dismiss, unsure = you decide), triage-check → fix → CI again … ≤ 3 rounds
 10 Video        (suggested for every frontend change; skipped only when you say no) one Playwright recordVideo run → video/BTRC-1234.webm; never blocks
 11 Finish       done by the orchestrator in the worktree: commit (title only: feat(<service>): …), pull --rebase,
                 force-push with a lease, glab pipeline must pass, containers down
 12 summary.md   then ExitWorktree + worktree.py remove --done: feature folder copied to the main checkout, worktree closed
```

Dropped connection? `claude --continue`, then `/feature resume BTRC-1234`. Every step writes `state.md` first, so nothing is lost.

---

## Setup (Ubuntu, user level)

Requirements: `python3` ≥ 3.10, `git`, and in the monorepo `uv` (with `ruff`, `mypy`, `pytest-cov`, `diff-cover` as dev dependencies of each Python service), the frontend's `eslint` in `node_modules`, `glab` logged in, and `docker compose`.

Everything lives plainly under `~/.claude/`, copied from this repo by hand:

| From the repo | To |
|---|---|
| `commands/*.md` | `~/.claude/commands/` (`/feature`, `/map-library`) |
| `agents/*.md` | `~/.claude/agents/` |
| `skills/*` | `~/.claude/skills/` |
| `scripts/**/*.py` | `~/.claude/scripts/` (executable) |
| `settings/hooks.json` | the `hooks` of `~/.claude/settings.json` |

Then copy the CLAUDE.md drafts from `claude-md/` into the monorepo (see `claude-md/README.md`).

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

## Worktrees and Claude Code's isolation

After `worktree.py create`, the orchestrator calls Claude Code's `EnterWorktree` tool with the worktree path (under `.claude/worktrees/`, so no approval). That moves the session's directory, write access and project config (folder `CLAUDE.md` files, settings) into the worktree. While inside, Claude Code refuses edits to the main checkout, Bash whose directory is the main checkout, and git redirected there. Therefore:
- **Each worktree keeps its own docs.** `worktree.py create <T> --branch <B> --base <base>` writes the feature folder straight into the worktree (`<worktree>/docs/features/<T>/` and `<worktree>/docs/features/.active`, git-ignored through the shared `.git/info/exclude`), so state.md, the spec, the test plan, the reviews, the subagents' files, the summary and the video are written there and never in the main checkout. Several features in parallel each have their own folder and `.active`. (A feature folder left in the main checkout by an older version is moved into the worktree.)
- Hooks get the worktree as payload `cwd` (`${CLAUDE_PROJECT_DIR}` stays at the main checkout), so they find that worktree's feature. From the main checkout, `feature_state` looks through `.claude/worktrees/*/docs/features/` (found with `git rev-parse --git-common-dir`) and picks the feature whose `Session:` is the asking session, else the only unfinished one.
- Finishing runs inside the worktree and **keeps it**, with its docs. Remove it later from the main checkout with `worktree.py remove <T>` (the branch stays; the feature folder goes with the worktree). The base in the main checkout isn't pulled for a worktree feature.
- `worktree.py create` copies the gitignored files listed in `.worktreeinclude` (gitignore syntax, e.g. `.env`) into the worktree, as Claude Code does for worktrees it creates itself. `.claude/worktrees/` stays in `.git/info/exclude` (the docs suggest `.gitignore`; either works).
- If your Claude Code version has no `EnterWorktree`, the orchestrator stays in the main checkout and works with absolute paths into the worktree. Then the worktree's folder `CLAUDE.md` files may not load (the docs treat files under `.claude/worktrees/` specially); the orchestrator reads them itself before editing a folder.

## The hooks

All four are user-level, so they run in every repository. Each exits 0 at once when `WORKFLOW_ROLE=reviewer`.

| Hook | When | What |
|---|---|---|
| `post_edit_checks.py` | After every Write/Edit | Only while an approved, unfinished feature is active for that repo (or with `WORKFLOW_CHECKS=1`), and only for files in its code root (the worktree, or the main checkout with `--no-worktree`). Runs the convention checker + `ruff` (`.py`/`.pyi`) or `eslint` (`.vue`/`.ts`/`.js`/…), and the suppression check (code and tool configs). Reports **only problems touching changed lines**: `git diff -U0 <merge-base with the base> -- <file>`; the whole file when it's untracked. `get_` names that existed in the base version aren't reported. |
| `guard_test_plan.py` | Before Write/Edit of a test file | Only for an approved, unfinished feature: blocks a new test whose exact name isn't in the first column of `test-plan.md`. |
| `guard_branch.py` | Before every Bash command, everywhere | On `checkout -b/-B/--orphan`, `switch -c/-C/--create[=]`, `branch <name>`, `branch -m`, `worktree add [-b]` (also without `-b`, where the branch is the folder name), `push <remote> <src>:<name>` (not deletes) — also inside `bash -c "…"`, after `VAR=…`/`sudo`/`env`, in `( … )` or after `&` — it fetches (15 s, no prompts) and blocks if another local or remote branch has the same `BTRC-<n>`. If the fetch fails it still checks and says the remote refs may be stale. |
| `next_step.py` | Stop | After approval, refuses to stop until `state.md` says `DONE` or `BLOCKED`, and returns the next step for the current `Phase`. It records the orchestrator's `session_id` as `Session:` on the first stop and ignores other sessions. Never blocks before approval or while a long script runs (`.running.json`). Circuit breaker: after 8 blocks without `state.md` changing it writes `BLOCKED: no progress`; the counter resets whenever a stop is allowed. |

Hooks also accept `"onFailure": "block"` (block the action when the hook itself crashes or times out). It isn't set on any of these: `guard_branch` fetches from a remote that may be unreachable offline, and a timeout must not stop all Bash commands.

### Environment variables

- `WORKFLOW_ROLE=reviewer`: a session with it set isn't blocked, checked or kept running by the orchestrator's hooks (for a reviewer you run by hand with `claude -p`). Don't set it in your own sessions.
- `WORKFLOW_CHECKS=1`: run the post-edit checks outside a feature too (e.g. while you edit by hand).

## The workflow scripts

Run from the repository root (the folder that holds `docs/features/`) as `python3 "$HOME/.claude/scripts/<name>.py"`. All read the branch, base, worktree, compose project/files from `docs/features/<ticket>/state.md`.

| Script | Does | Exit codes |
|---|---|---|
| `worktree.py create <T> --branch <B> --base <base> [--title "…"] [--no-worktree]` · `remove <T>` | `create` fetches the base and runs `git worktree add -b <Branch> .claude/worktrees/<Branch> origin/<Base>`, or `git worktree add .claude/worktrees/<Branch> <Branch>` when the branch exists (locally or on origin); it never creates a second branch for the same BTRC-n. With `--no-worktree` it switches the main checkout to the branch (creating or reusing it). It keeps `.claude/worktrees/` and `docs/features/` in `.git/info/exclude` and records `Worktree:` / `Worktree mode:`; if the worktree already exists it only records it. A new feature (`--branch`, `--base`, `--title`) gets its state.md written in the code root; an existing one is moved into the worktree. It also copies `.worktreeinclude` files. `remove` copies the feature folder into the main checkout's `docs/features/`, then removes the worktree (the branch stays); `--done` also sets `Status: DONE`. Its git calls don't pass through the Bash hook. | 0 · 1 git failed · 2 setup (incl. another branch for the ticket) |
| `workflow_note.py --author <who> --kind <k> --source <s> --what "<…>" --suggestion "<…>"` · `--show` | Appends a note about the workflow itself (a rule, skill, script, hook or agent that was wrong, unclear or missing) to `~/.claude/workflow-feedback/<branch>/<author>.md`, with the time and the active ticket and phase: one folder per branch, one file per writer (the orchestrator, each reviewer, each verifier), so parallel agents never share a file. Reviewers' notes never reach the orchestrator. You review the folder to improve the workflow. `WORKFLOW_FEEDBACK_DIR` moves it. | 0 · 2 setup |
| `check_changes.py [--base <base>]` · `check_changes.py --slice <T> <n>` | Changed-line checks (conventions, comments, Vue rules, ruff, eslint, `mypy --strict`, suppressions), run in parallel. Run it before **every** commit to a feature branch (base: `--base`, else the feature's `Base:`, else origin/HEAD). With `--slice` it also fails on changed, deleted or renamed files outside plan.md's slices 1..n, lists changed existing lines, and advances `Slice`/`Phase` on pass. | 0 pass · 1 problems · 2 setup (incl. git errors, unknown base) |
| `check_vue_conventions.py <files>` | Vue rules eslint can't see, on `.vue` files: values in `<script lang="ts">` (VU-05), single-use string constants (VU-22), non-theme colors (VU-16), `w-[100%]`/px font sizes (VU-54), px sizes (VU-18), `d-*` classes (VU-43), `let` state (VU-36). Run by `line_checks.py`, so `check_changes` reports it on changed lines. | 0 · 1 |
| `review_round.py expected <T> <round>` · `capture <T> <round> --source <s>` · `verify-check <T> <round> --source <s>` · `triage-check <T> <round>` | `expected` prints the round's reviewers. `capture` checks `review/<s>-<round>.md` (every `## ` line is a finding `## <id> \| <file:line> \| <rule>` of that source and round, and the last `Done: <k> finding(s)` matches) and stores the findings with each flagged line's text in `<s>-<round>.json`, noting earlier dismissals. `verify-check` checks `review/verify-<s>-<round>.md` gives every finding exactly one `sure`/`unsure`/`invalid`. `triage-check` checks every expected source is captured and verified and every finding has a triage.md row whose Verdict matches and whose Decision follows it (sure → fix, invalid → dismiss, unsure → either, a dismiss with a Reason). A source failing capture or verify-check 3 times in a row blocks the feature. | 0 · 1 incomplete · 2 setup |

Each script counts failed runs in `Tries:`; the third failed run of the same step (or the same finish code) writes `BLOCKED`. Exit 30 blocks at once.

Outside the workflow you can still run:
```bash
python3 "$HOME/.claude/scripts/check_python_conventions.py" app/
```
```bash
python3 "$HOME/.claude/scripts/mypy_strict.py" app/
```

## Not verified offline

These need checking in the work environment; each has an isolated spot to adjust.

| Point | Where to adjust |
|---|---|
| `glab ci status --branch <b>` flags and output (`Pipeline state:`, `SHA:`, tab-separated `(failed)` job lines), and `glab ci trace <job> --branch <b>`. `glab ci get -b <b> -F json` may be the sturdier source. | `commands/feature.md` step F |
| `EnterWorktree` exists in the work environment's Claude Code version, and the isolation rules match the docs (code.claude.com/docs/en/worktrees). Without them the fallback above applies. | `commands/feature.md` steps S and F |
| `$HOME` is expanded in the hook commands (they run through a shell). | `settings/hooks.json` |
| The Playwright reviewer and the video: no frontend repo or Playwright on this machine. The agent loads Playwright from the frontend folder with `require(require.resolve('playwright', { paths: [...] }))` from a script in `docs/features/<T>/playwright/`, uses only preinstalled browsers, and mocks the API with `page.route()` or uses the branch's docker stack. `recordVideo` output naming, the dev-server start/stop and the login flow need a real run. | `agents/playwright-reviewer.md`, `commands/feature.md` step V |
| The HTML mockups use CSS `:has()` for the theme/RTL/state switches (no JavaScript); the offline browser must support it (Chromium 105+, Firefox 121+). | `skills/html-mockups/templates/mockup.html` |
| `.claude/rules/*.md` with a `paths:` glob, as an alternative to folder CLAUDE.md files. | `claude-md/README.md` |
| The monorepo paths in `claude-md/`, the `## Commands` lines, and `Compose files`. | each feature's `state.md` |

## Developing

```bash
uv run --with pytest pytest tests -q
```

The tests mock `glab`, `docker` and `claude` at `command_runner.run_command`; git runs for real (temporary repositories, a bare remote and a worktree for the finish tests). The install tests and the process-group tests run only on Linux.
