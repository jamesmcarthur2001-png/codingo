---
description: "One-session feature workflow for BTRC tickets: setup + worktree, 3 parallel explorers, grill, spec + slice plan, ONE approval, then autonomous build per slice, tests, Gate A, Beatrice (up to 5 rounds), finish script, summary. Driven by docs/features/<ticket>/state.md and the Stop hook."
argument-hint: "<BTRC-n> \"<description>\" [base] | resume <BTRC-n>"
---

# /feature

Request: `$ARGUMENTS`

You are the orchestrator. You do every step yourself, in this one session. Subagents are used only for exploration (step E).

## Rules (always)
1. `state.md` is the truth. Update it after every step, before the next one. After a compaction, read it again.
2. Run every script from the **repository root** (the directory holding `docs/features/`):
   `python3 "$HOME/.claude/midnight-workflow/scripts/<name>.py" <TICKET> ...`
3. Code lives in the **worktree** (`Worktree:` in state.md, inside the repo at `.worktrees/BTRC-<n>`). Edit files there. Run git and project commands there with `git -C "<Worktree>" ...` or a subshell `(cd "<Worktree>" && ...)`. Never leave the shell in another directory with a bare `cd`.
4. Scope: new code follows the conventions. Existing lines change only when the task needs them changed. Never rename, reformat or "fix" existing code you don't need to touch.
5. Say something works or passes only after you ran the check, and show its output. If you can't check it, say so.
6. Before approval you may ask the user anything. **After approval never ask the user anything.** Decide conservatively, write the decision in `## Log`, continue.
7. Try limits: a step fails → fix → run again. The scripts write `Status: BLOCKED: <reason>` on the 3rd failed run of the same step. For steps without a script (tests), do the same yourself. When Status is BLOCKED: tell the user the reason and stop.
8. While `run_beatrice.py`, `gate_a.py` or `finish_branch.py` runs, don't edit state.md; wait for it to finish. A second run of the same feature refuses to start (exit 2) while one is running.
9. Don't commit during the build. `finish_branch.py` makes the commit.
10. Any `docker compose` command for this branch uses `-p <Compose project>` and the files in `Compose files:`.
11. Never add `# noqa`, `# type: ignore`, `# pylint: disable`, `eslint-disable`, `@ts-ignore`, `@ts-expect-error` or `# pragma: no cover`. Fix the code instead.

## state.md format
Top fields are `Name: value` lines before the first `## `. Change one by rewriting its line.

| Field | Values |
|---|---|
| `Phase` | before approval: `SETUP`, `EXPLORE`, `GRILL`, `SPEC` · after: `BUILD`, `TESTS`, `GATE-A`, `GATE-B`, `FINISH`, `SUMMARY` |
| `Status` | `RUNNING`, `DONE`, `BLOCKED: <reason>` |
| `Approved` | `no` until the user approves, then `yes` |
| `Session` | empty; the Stop hook writes this session's id after approval and then acts only for this session |
| `Slice` / `Slices` | current slice / number of slices in plan.md |
| `Round` | Beatrice round, 1–5 |
| `Tries` | `0`, or `<STEP> <failed runs>` (e.g. `TESTS 1`) |

Phases after approval: BUILD, TESTS, GATE-A, GATE-B, FINISH, SUMMARY

---

## Arguments
- `BTRC-<n> "<description>" [base]` → start at **S**.
- `resume BTRC-<n>` → go to **R**.

## R. Resume
1. Read `docs/features/BTRC-<n>/state.md`. If missing: tell the user and stop.
2. Write `BTRC-<n>` into `docs/features/.active` if it isn't there.
3. If `Status` starts with `BLOCKED`: show the reason and the last 10 `## Log` lines, and stop.
4. If `Status: DONE`: show `summary.md` and stop.
5. Clear the `Session:` field (this is a new session; the Stop hook records the new id).
6. Continue at the step for `Phase` (SETUP→S, EXPLORE→E, GRILL→G, SPEC→P, BUILD→B, TESTS→T, GATE-A→A, GATE-B→GB, FINISH→F, SUMMARY→Z). Skip work whose output file already exists and is complete.
7. Tell the user once: if the connection drops, recover with `claude --continue`, then `/feature resume BTRC-<n>`.

## S. Setup (Phase: SETUP)
1. Ticket = `BTRC-<n>` (uppercase). Title = the description.
2. Base = the `[base]` argument, else `git branch --show-current`.
3. Branch = `BTRC-<n>-<2-4 word kebab-case summary>`, e.g. `BTRC-1234-csv-export`.
4. Repo root = `git rev-parse --show-toplevel`. Worktree = `<repo root>/.worktrees/BTRC-<n>`.
5. Keep the workflow's folders out of git without touching tracked files: append `docs/features/` and `.worktrees/` to `.git/info/exclude` if they aren't there. Never edit `.gitignore`.
6. Create the worktree:
   ```
   git fetch origin
   git worktree add -b <Branch> "<Worktree>" <Base>
   ```
   If the `guard_branch` hook blocks it, a branch for this BTRC-n already exists: tell the user and stop. Never work around it.
7. Create `docs/features/BTRC-<n>/` and write `docs/features/.active` with one line: `BTRC-<n>`.
8. Find Beatrice's command file: `.claude/commands/beatrice-code-review.md` in the repo, else `~/.claude/commands/beatrice-code-review.md`. If neither exists, keep the placeholder below and ask the user for the path during the grill.
9. Fill `## Commands` from the `service-map` skill and the root/service `CLAUDE.md`. Each runs in the worktree through `bash -lc`. Names starting with `coverage` must print diff-cover output and pass `--include-untracked` (new files stay untracked until finish). The test command must write the coverage report the coverage command reads. Example:
   ```
   - lint: npx nx affected -t lint --base=origin/<Base>
   - typecheck: npx nx affected -t typecheck --base=origin/<Base>
   - test: npx nx affected -t test --base=origin/<Base>
   - coverage-backend: diff-cover services/evermore/coverage.xml --compare-branch=origin/<Base> --include-untracked --fail-under=100
   ```
   If the service map is missing or mostly `TODO`, say that `/map-services` gives better results, and use what CLAUDE.md says.
10. `Compose files:` = the `-f` files you use to start this branch's containers (space-separated, relative to the worktree), e.g. `docker-compose.yml docker-compose.dev.yml`. Start containers only with `docker compose -p <Compose project> -f <each file> up -d`.
11. Write `docs/features/BTRC-<n>/state.md`:
    ```markdown
    Ticket: BTRC-1234
    Title: add CSV export to entities
    Branch: BTRC-1234-csv-export
    Base: master
    Worktree: .worktrees/BTRC-1234
    Compose project: btrc-1234
    Compose files: docker-compose.yml
    Beatrice command: /home/<you>/.claude/commands/beatrice-code-review.md
    Beatrice mode: slash
    Approved: no
    Session:
    Phase: EXPLORE
    Slice: 1
    Slices:
    Round: 1
    Tries: 0
    Status: RUNNING

    ## Commands
    - lint: <command>
    - typecheck: <command>
    - test: <command>
    - coverage-backend: <command>

    ## Coverage exemptions

    ## Log
    - <DD/MM/YYYY HH:MM> setup done: worktree <Worktree> on <Base>
    ```
    - `Worktree` may be relative to the repo root (as above) or absolute.
    - `Compose project` = `btrc-<n>` (lowercase).
    - `Beatrice mode`: `slash` runs `/beatrice-code-review <Base>`; `file` passes the file's text as the prompt. The script switches to `file` by itself for a round when `claude -p` doesn't know the slash command. Optional field `Beatrice tools: <--allowedTools value>` overrides the default read-only tool list.
    - Leave `Slices:` and `Session:` empty.
12. Show the output of `git -C "<Worktree>" status` and `git worktree list`.

## E. Explore (Phase: EXPLORE)
1. Start 3 `explorer` agents **in one message** (parallel). Same prompt for each, only `n` differs:
   ```
   Feature: <Ticket> "<Title>"
   Feature directory: <repo root>/docs/features/<Ticket>
   Code root: <repo root>/<Worktree>
   Your number n: <1|2|3>
   Explore the whole scope of this feature. Write only explore/explorer-<n>.md.
   ```
2. Wait for all 3. Check that `explore/explorer-1.md`, `-2.md`, `-3.md` exist. If one is missing, run that one again once; if it still fails, continue with the others and log it.
3. Merge them yourself. Same item from several explorers = one item. Mark each item with how many found it: `(3/3)`, `(2/3)`, `(1/3)`. Never drop an item because only one explorer found it.
   - `context.md`: `# Context: <feature>`, then the sections Services touched, Files likely to change, Similar existing features, Integration points, Tooling (incl. commands), Risks.
   - `patterns.md`: `# Patterns: <feature>`, then `## P-1 <name>` … (Reference, Shape, Tested by, mark), then `## Inconsistencies` with `I-1` ….
4. Check every `(1/3)` item in the code now: open the cited file. Change the mark to `(1/3, checked)` or `(1/3, wrong: <why>)`. Rely only on checked items.
5. `patterns.md` must have at least one `P-n`. If not, explore that part yourself.
6. If the explorers found better commands than `## Commands`, update them. Set `Phase: GRILL`.

## G. Grill (Phase: GRILL)
1. Load the `grill-with-docs` skill and follow it fully with the user. Input: the description, `context.md`, `patterns.md`.
2. Every inconsistency `I-n` must end as a decision.
3. Ask for the Beatrice command path here if setup didn't find it.
4. It ends when `grill-notes.md` has no open or assumed unknowns and the user confirmed the readback. Set `Phase: SPEC`.

## P. Spec, plan, approval (Phase: SPEC)
1. Load the `write-spec` skill. Write `spec.md` and `plan.md` yourself (no subagent), from its templates. The first line of spec.md is `# Spec: <feature name>` (it becomes the commit title).
2. `plan.md` format (the scripts parse it):
   ```markdown
   ## Slice 1: <name>
   Files:
   - `services/evermore/app/entities/export.py`
   - `services/evermore/app/routers/`
   Covers: REQ-1, EC-2
   Pattern: P-2 (`services/evermore/app/entities/reader.py`)
   Tasks:
   - <concrete step>
   Verify: `<command>`
   ```
   - 2–4 slices. Paths are relative to the repo root. Folders end with `/`; `*` matches inside one folder, `**` across folders.
   - `Files:` lists every file the slice may change. No other headers inside a slice.
   - Test files are not listed here (they come from test-plan.md).
3. Run the write-spec self-check. Fix what fails.
4. Check `## Commands`, `Compose files` and `Beatrice command` in state.md are final.
5. Approval is your **last question**. Show: goal, number of REQs/ECs/slices, every `NEW` pattern, the riskiest decision, the paths of spec.md and plan.md. Ask with `AskUserQuestion`: "Approve the spec and plan?" → "Approve and start (Recommended)" / "I have changes". On changes: edit, ask again.
6. On approval, set in state.md: `Approved: yes`, `Phase: BUILD`, `Slice: 1`, `Slices: <number of slices>`, `Tries: 0`. Set `Status: APPROVED (<DD/MM/YYYY>)` in spec.md and plan.md.
7. From now on: no questions. The Stop hook will refuse to let you stop until Status is DONE or BLOCKED, and tells you the next step.

## B. Build (Phase: BUILD), for slice = `Slice`
1. Read the slice in plan.md: Files, Covers, Pattern, Tasks.
2. Load the per-topic checklists for what the slice touches (each is short):
   - Python: every `~/.claude/skills/python-conventions/references/checklist-*.md`
   - Vue/TS: `~/.claude/skills/vue-conventions/references/checklist.md`
   - Code that uses a database session: `~/.claude/skills/sql-conventions/references/checklist.md`
3. Load the conventions skill for each stack (`python-conventions`, `vue-conventions`, and `sql-conventions` for database code) and read the `CLAUDE.md` of every folder you edit (root, service, `tests/`).
4. Open the pattern's reference file and mirror its structure.
5. Implement the tasks. Change only files in the slice's `Files:`. The post-edit hook reports problems on your changed lines: fix them right away.
6. Run:
   ```
   python3 "$HOME/.claude/midnight-workflow/scripts/check_slice.py" <Ticket> <Slice>
   ```
   Exit 0: it already set the next `Slice` (or `Phase: TESTS` after the last slice). Continue.
   Exit 1: fix every listed `file:line`, run it again. A file outside the list: revert it, or add it to the slice's `Files:` with a reason in `## Log`.
   "Existing lines you changed" is not a failure: check each one was needed; restore it if not.
   Exit 2: setup error (plan.md, state.md, or git). Fix the cause from the message, run again.
7. Spec doesn't cover a case → choose the most conservative option that fits the spec, log it as `DEV-n` in `## Log`, continue.

## T. Tests (Phase: TESTS)
1. Load the `test-plan` skill. Write `test-plan.md` as **one table with exactly four columns**:
   ```markdown
   | Test name | What it checks | Expected result | File |
   |---|---|---|---|
   | `test_entity_by_id_missing_id_raises_entity_not_found_error` | Reading an entity id that doesn't exist | Raises `EntityNotFoundError` with "Entity 7 was not found." | `services/evermore/tests/entities/test_read_entity.py` |
   ```
   Test name = the exact pytest function name / `it(...)` / `test(...)` string. File = path relative to the **repo root**. Cover every REQ, EC and new code path. No `|` inside a cell.
2. Write the tests. Load before each kind: `pytest-conventions` + `backend-test-infra` (backend), `vitest-conventions` (frontend), `browser-test-conventions` (Playwright). A service's `tests/CLAUDE.md` wins over the skills.
3. The test-plan hook blocks any test whose exact name isn't in the first column. Add the row first, then write the test.
4. Test helper files (conftest, environment builders, factories, MSW handlers) that aren't in the File column: add them to the last slice's `Files:` in plan.md and log why.
5. Run the `test` command and every `coverage*` command from `## Commands`, in the worktree.
   - Failing test that shows a real bug → fix the code, log it.
   - Changed lines without coverage → add a planned test. Only if a line truly can't be tested, add `- path:lines: reason` under `## Coverage exemptions`, with the full repo-relative path (e.g. `- services/evermore/app/x.py:40-42: unreachable after the validator`).
6. Limit: after a failed run set `Tries: TESTS <failed runs>`. On the 3rd failed run write `Status: BLOCKED: tests fail after 2 fixes` and stop.
7. All green: set `Tries: 0`, `Phase: GATE-A`.

## A. Gate A (Phase: GATE-A)
1. Run (it can take long; use the maximum Bash timeout, 600000 ms, or run it in the background and wait):
   ```
   python3 "$HOME/.claude/midnight-workflow/scripts/gate_a.py" <Ticket>
   ```
   It runs lint, typecheck, tests, changed-line coverage, scope and suppression checks.
2. Exit 0: it set the next phase. Normally `Phase: GATE-B` (go to GB). After round 5 was triaged it sets `Phase: FINISH` (go to F).
3. Exit 1: fix every item, run again. Uncovered lines → a test (add its row first) or an exemption with a reason.
4. Exit 2: setup error (`## Commands` missing, a coverage command without `--include-untracked`, the feature can't be found, git failed, or another run is still going). Fix the cause, run again.

## GB. Gate B, Beatrice (Phase: GATE-B), round = `Round`
1. If `review/triage.md` already has `## Round <Round>`, this round is triaged: skip to step 5.
2. If `review/beatrice-<Round>.md` already exists, skip to step 4.
3. Run it **in the background** (Bash `run_in_background: true`) and wait for the notification:
   ```
   python3 "$HOME/.claude/midnight-workflow/scripts/run_beatrice.py" <Ticket> <Round>
   ```
   Exit 0: read `review/beatrice-<Round>.md` (findings `## R<round>-<i> | <2/2 or 1/2> | <file:line> | <rule>`).
   Exit 1: both runs failed; run it again (the script blocks after 3 failures).
   Exit 2: setup error (feature not found, or another run is still going). Fix the cause, run again.
4. Triage. For every finding, open the code and check it yourself. 1/2 counts as much as 2/2. A finding marked "Dismissed in round N, because …" keeps that decision unless the line changed. Append to `review/triage.md` (the `#` column is the finding's id from beatrice-<Round>.md):
   ```markdown
   ## Round <Round>
   | # | Marks | File:line | Rule | Finding | Decision | Reason |
   |---|---|---|---|---|---|---|
   | R1-1 | 2/2 | services/evermore/app/x.py:40 | PY-03 | missing None check | fix | |
   | R1-2 | 1/2 | services/evermore/app/x.py:52 | no rule | rename variable | dismiss | line 52 is unchanged legacy code (scope rule) |
   ```
   `dismiss` needs a Reason pointing to a line or a rule. No `|` inside a cell.
5. Next:
   - No `fix` rows this round → set `Phase: FINISH`.
   - `fix` rows and `Round` < 5 → fix them all, then set `Round: <Round+1>` and `Phase: GATE-A`.
   - `fix` rows and `Round` = 5 → fix them, keep `Round: 5`, set `Phase: GATE-A`. Gate A then sets `Phase: FINISH`. Leftovers go into the summary.

## F. Finish (Phase: FINISH)
1. Run **in the background** and wait for the notification (it waits up to 45 min for the pipeline):
   ```
   python3 "$HOME/.claude/midnight-workflow/scripts/finish_branch.py" <Ticket>
   ```
   It checks the worktree is on `Branch` (never the base), commits, `git pull --rebase origin <Base>`, pushes `HEAD:refs/heads/<Branch>` with a lease on the last pushed commit, waits for the pipeline, runs `docker compose -p <Compose project> -f … down --remove-orphans`, removes the worktree, and updates the base in the main checkout. Running it again resumes.
2. Act on the exit code:
   | Code | Do |
   |---|---|
   | 0 | It set `Phase: SUMMARY`. Go to Z. |
   | 10 | Rebase conflict: resolve the listed files in the worktree (remove every `<<<<<<<`/`>>>>>>>` marker), `git -C "<Worktree>" add <files>`, run the `test` command, run the script again. Don't run `git rebase --continue` yourself. |
   | 20 | Pipeline failed: fix the cause from the log tail in the worktree, run the tests, run the script again. |
   | 30 | Push rejected: someone else pushed. The script wrote BLOCKED. Stop. |
   | 1 | Read the message, fix the cause, run again. |
   | 2 | Setup error (state.md fields, wrong branch checked out, or another run is still going). Fix the cause, run again. |
   The script writes BLOCKED itself after 3 runs with the same code.

## Z. Summary (Phase: SUMMARY)
1. Write `docs/features/<Ticket>/summary.md`:
   ```markdown
   # Summary: <Ticket> <feature>
   ## Built
   - REQ-1 … (files)
   ## Deviations
   - DEV-n … (from ## Log)
   ## Tests
   - <n> tests · changed-line coverage: <result> · exemptions: <list or none>
   ## Beatrice
   | Round | # | Marks | File:line | Finding | Outcome (fixed / dismissed: reason / left open) |
   ## Finish
   - Branch <Branch> pushed · pipeline <result> · worktree removed · base updated
   ## Needs your attention
   - <anything open, risky or left undone>
   ```
   List **every** Beatrice finding from every round.
2. Set `Status: DONE` in state.md. Delete `docs/features/.active`.
3. Show the user the summary and the feature folder path.
