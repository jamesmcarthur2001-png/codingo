---
description: "One-session feature workflow for BTRC tickets: setup + worktree, 3 parallel explorers, grill, spec + slice plan, ONE approval, then autonomous build per slice, tests, Gate A, Beatrice (up to 5 rounds), finish script, summary. Driven by docs/features/<ticket>/state.md and the Stop hook."
argument-hint: "<BTRC-n> \"<description>\" [base] | resume <BTRC-n>"
---

# /feature

Request: `$ARGUMENTS`

You are the orchestrator. You do every step yourself, in this one session. Subagents are used only for exploration (step E).

## Rules (always)
1. `state.md` is the truth. Update it after every step, before the next one. After a compaction, read it again.
2. Run every script from the **repository root** (the directory holding `docs/features/`), never from inside the worktree:
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py" <TICKET> ...`
3. Code lives in the **worktree** (`Worktree:` in state.md). Edit files there. Run git and project commands there with `git -C "<worktree>" ...` or `cd "<worktree>" && ...` inside one command. Don't leave the shell inside the worktree.
4. Scope: new code follows the conventions. Existing lines change only when the task needs them changed. Never rename, reformat or "fix" existing code you don't need to touch.
5. Say something works or passes only after you ran the check, and show its output. If you can't check it, say so.
6. Before approval you may ask the user anything. **After approval never ask the user anything.** Decide conservatively, write the decision in `## Log`, continue.
7. Try limits: a step fails → fix → run again. The scripts write `Status: BLOCKED: <reason>` on the 3rd failed run of the same step. For steps without a script (tests), do the same yourself. When Status is BLOCKED: tell the user the reason and stop.
8. While `run_beatrice.py` or `finish_branch.py` runs in the background, **do not edit state.md** (the script rewrites it when it ends). Wait for the notification.
9. Don't commit during the build. `finish_branch.py` makes the commit.
10. Any `docker compose` command for this branch uses `-p <Compose project>`.

## state.md format
Top fields are `Name: value` lines before the first `## `. Change one by rewriting its line.

| Field | Values |
|---|---|
| `Phase` | before approval: `SETUP`, `EXPLORE`, `GRILL`, `SPEC` · after: `BUILD`, `TESTS`, `GATE-A`, `GATE-B`, `FINISH`, `SUMMARY` |
| `Status` | `RUNNING`, `DONE`, `BLOCKED: <reason>` |
| `Approved` | `no` until the user approves, then `yes` |
| `Slice` / `Slices` | current slice / number of slices in plan.md |
| `Round` | Beatrice round, 1–5 |
| `Tries` | `0`, or `<STEP> <failed runs>` (e.g. `TESTS 1`) |

---

## Arguments
- `BTRC-<n> "<description>" [base]` → start at **S**.
- `resume BTRC-<n>` → go to **R**.

## R. Resume
1. Read `docs/features/BTRC-<n>/state.md`. If missing: tell the user and stop.
2. Write `BTRC-<n>` into `docs/features/.active` if it isn't there.
3. If `Status` starts with `BLOCKED`: show the reason and the last 10 `## Log` lines, and stop.
4. If `Status: DONE`: show `summary.md` and stop.
5. Continue at the step for `Phase` (SETUP→S, EXPLORE→E, GRILL→G, SPEC→P, BUILD→B, TESTS→T, GATE-A→A, GATE-B→GB, FINISH→F, SUMMARY→Z). Skip work whose output file already exists and is complete.
6. Tell the user once: if the connection drops, recover with `claude --continue`, then `/feature resume BTRC-<n>`.

## S. Setup (Phase: SETUP)
1. Ticket = `BTRC-<n>` (uppercase). Title = the description.
2. Base = the `[base]` argument, else `git branch --show-current`.
3. Branch = `BTRC-<n>-<2-4 word kebab-case summary>`, e.g. `BTRC-1234-csv-export`.
4. Repo root = `git rev-parse --show-toplevel` (forward slashes, e.g. `C:/work/midnight-api`). Worktree = `<repo root>-BTRC-<n>`, e.g. `C:/work/midnight-api-BTRC-1234`.
5. Create the worktree:
   ```
   git fetch origin
   git worktree add -b <Branch> "<Worktree>" <Base>
   ```
   If the `guard_branch` hook blocks it, a branch for this BTRC-n already exists: tell the user and stop. Never work around it.
6. Keep `docs/features/` out of git without touching tracked files: if `.git/info/exclude` has no line `docs/features/`, append it. Never edit `.gitignore`.
7. Create `docs/features/BTRC-<n>/` and write `docs/features/.active` with one line: `BTRC-<n>`.
8. Find Beatrice's command file: `.claude/commands/beatrice-code-review.md` in the repo, else `~/.claude/commands/beatrice-code-review.md`. If neither exists, keep the placeholder below and ask the user for the path during the grill.
9. Fill `## Commands` from the `service-map` skill and the root/service `CLAUDE.md`. Each runs in the worktree. Names starting with `coverage` must print diff-cover output. The test command must write the coverage report the coverage command reads. Example:
   ```
   - lint: npx nx affected -t lint --base=origin/<Base>
   - typecheck: npx nx affected -t typecheck --base=origin/<Base>
   - test: npx nx affected -t test --base=origin/<Base>
   - coverage-backend: diff-cover services/evermore/coverage.xml --compare-branch=origin/<Base> --fail-under=100
   ```
   If the service map is missing or mostly `TODO`, say that `/midnight-workflow:map-services` gives better results, and use what CLAUDE.md says.
10. Write `docs/features/BTRC-<n>/state.md`:
    ```markdown
    Ticket: BTRC-1234
    Title: add CSV export to entities
    Branch: BTRC-1234-csv-export
    Base: master
    Worktree: C:/work/midnight-api-BTRC-1234
    Compose project: btrc-1234
    Beatrice command: C:/path/to/beatrice-code-review.md
    Beatrice mode: slash
    Approved: no
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
    - `Compose project` = `btrc-<n>` (lowercase).
    - `Beatrice mode`: `slash` runs `/beatrice-code-review <Base>`; `file` passes the file's text as the prompt (use it if `claude -p` can't run the slash command). Optional field `Beatrice tools: <--allowedTools value>` overrides the default tool list.
    - Leave `Slices:` empty until approval.
11. Show the output of `git -C "<Worktree>" status` and `git worktree list`.

## E. Explore (Phase: EXPLORE)
1. Start 3 `midnight-workflow:explorer` agents **in one message** (parallel). Same prompt for each, only `n` differs:
   ```
   Feature: <Ticket> "<Title>"
   Feature directory: <repo root>/docs/features/<Ticket>
   Code root: <Worktree>
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
2. `plan.md` format (the scripts parse it; this wins over the skill's task rules):
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
   - 2–4 slices. Paths are relative to the repo root, forward slashes. Folders end with `/`; globs are allowed.
   - `Files:` lists every file the slice may change. No other headers inside a slice.
   - Test files are not listed here (they come from test-plan.md).
3. Run the write-spec self-check. Fix what fails.
4. Check `## Commands` and `Beatrice command` in state.md are final.
5. Approval is your **last question**. Show: goal, number of REQs/ECs/slices, every `NEW` pattern, the riskiest decision, the paths of spec.md and plan.md. Ask with `AskUserQuestion`: "Approve the spec and plan?" → "Approve and start (Recommended)" / "I have changes". On changes: edit, ask again.
6. On approval, set in state.md: `Approved: yes`, `Phase: BUILD`, `Slice: 1`, `Slices: <number of slices>`, `Tries: 0`. Set `Status: APPROVED (<DD/MM/YYYY>)` in spec.md and plan.md.
7. From now on: no questions. The Stop hook will refuse to let you stop until Status is DONE or BLOCKED, and tells you the next step.

## B. Build (Phase: BUILD), for slice = `Slice`
1. Read the slice in plan.md: Files, Covers, Pattern, Tasks.
2. Load the short checklist of each stack the slice touches:
   - Python: `${CLAUDE_PLUGIN_ROOT}/skills/python-conventions/references/checklist.md`
   - Vue/TS: `${CLAUDE_PLUGIN_ROOT}/skills/vue-conventions/references/checklist.md`
3. Load the conventions skill (`python-conventions` / `vue-conventions`) and read the `CLAUDE.md` of every folder you edit (root, service, `tests/`).
4. Open the pattern's reference file and mirror its structure.
5. Implement the tasks. Change only files in the slice's `Files:`. The post-edit hook reports problems on your changed lines: fix them right away.
6. Run:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/check_slice.py" <Ticket> <Slice>
   ```
   Exit 0: it already set the next `Slice` (or `Phase: TESTS` after the last slice). Continue.
   Exit 1: fix every listed `file:line`, run it again. A file outside the list: revert it, or add it to the slice's `Files:` with a reason in `## Log`.
   "Existing lines you changed" is not a failure: check each one was needed; restore it if not.
   Exit 2: plan.md or state.md is wrong. Fix the format, run again.
7. Spec doesn't cover a case → choose the most conservative option that fits the spec, log it as `DEV-n` in `## Log`, continue.

## T. Tests (Phase: TESTS)
1. Load the `test-plan` skill. Write `test-plan.md` as **one table with exactly four columns** (this wins over the skill's template):
   ```markdown
   | Test name | What it checks | Expected result | File |
   |---|---|---|---|
   | `test_entity_by_id_missing_id_raises_entity_not_found_error` | Reading an entity id that doesn't exist | Raises `EntityNotFoundError` with "Entity 7 was not found." | `services/evermore/tests/entities/test_read_entity.py` |
   ```
   Test name = the exact pytest function name / `it(...)` / `test(...)` string. File = path relative to the repo root. Cover every REQ, EC and new code path. No `|` inside a cell.
2. Write the tests. Load before each kind: `pytest-conventions` + `backend-test-infra` (backend), `vitest-conventions` (frontend), `browser-test-conventions` (Playwright). A service's `tests/CLAUDE.md` wins over the skills.
3. The test-plan hook blocks any test not named in test-plan.md. Add the row first, then write the test.
4. Test helper files (conftest, environment builders, factories, MSW handlers) that aren't in the File column: add them to the last slice's `Files:` in plan.md and log why.
5. Run the `test` command and every `coverage*` command from `## Commands`, in the worktree.
   - Failing test that shows a real bug → fix the code, log it.
   - Changed lines without coverage → add a planned test. Only if a line truly can't be tested, add `- path:lines: reason` under `## Coverage exemptions` (e.g. `- services/evermore/app/x.py:40-42: unreachable after the validator`).
6. Limit: after a failed run set `Tries: TESTS <failed runs>`. On the 3rd failed run write `Status: BLOCKED: tests fail after 2 fixes` and stop.
7. All green: set `Tries: 0`, `Phase: GATE-A`.

## A. Gate A (Phase: GATE-A)
1. Run (it can take long; use the maximum Bash timeout, 600000 ms):
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/gate_a.py" <Ticket>
   ```
   It runs lint, typecheck, tests, changed-line coverage, scope and suppression checks.
2. Exit 0: it set `Phase: GATE-B`. Continue at GB.
3. Exit 1: fix every item, run again. Uncovered lines → a test (add its row first) or an exemption with a reason. Never add `# noqa`, `# type: ignore`, `# pylint: disable`, `eslint-disable`.
4. Exit 2: `## Commands` is missing or the feature can't be found. Fix state.md, run again.

## GB. Gate B, Beatrice (Phase: GATE-B), round = `Round`
1. If `review/beatrice-<Round>.md` already exists and has no triage yet, skip to step 3.
2. Run it **in the background** (Bash `run_in_background: true`) and wait for the notification. Don't edit state.md meanwhile:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/run_beatrice.py" <Ticket> <Round>
   ```
   Exit 0: read `review/beatrice-<Round>.md` (findings `## R<round>-<i> | <2/2 or 1/2> | <file:line> | <rule>`).
   Exit 1: both runs failed; run it again (the script blocks after 3 failures).
3. Triage. For every finding, open the code and check it yourself. 1/2 counts as much as 2/2. A finding marked "Dismissed in round N, because …" keeps that decision unless the line changed. Append to `review/triage.md`:
   ```markdown
   ## Round <Round>
   | # | Marks | File:line | Rule | Finding | Decision | Reason |
   |---|---|---|---|---|---|---|
   | R1-1 | 2/2 | services/evermore/app/x.py:40 | PY-3 | missing None check | fix | |
   | R1-2 | 1/2 | services/evermore/app/x.py:52 | no rule | rename variable | dismiss | line 52 is unchanged legacy code (scope rule) |
   ```
   `dismiss` needs a Reason pointing to a line or a rule. No `|` inside a cell.
4. Before fixing anything, record the dismissals (keyed by the flagged line's current text):
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/gate_a.py" <Ticket> --dismissed
   ```
5. Next:
   - No `fix` rows this round → set `Phase: FINISH`.
   - `fix` rows and `Round` < 5 → fix them all, then set `Round: <Round+1>` and `Phase: GATE-A`.
   - `fix` rows and `Round` = 5 → fix them, run Gate A until it passes, then set `Phase: FINISH`. Leftovers go into the summary.

## F. Finish (Phase: FINISH)
1. Run **in the background** and wait for the notification (it waits up to 45 min for the pipeline). Don't edit state.md meanwhile:
   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/finish_branch.py" <Ticket>
   ```
   It commits, `git pull --rebase origin <Base>`, pushes with `--force-with-lease`, waits for the pipeline, runs `docker compose -p <Compose project> down`, removes the worktree. Running it again resumes.
2. Act on the exit code:
   | Code | Do |
   |---|---|
   | 0 | It set `Phase: SUMMARY`. Go to Z. |
   | 10 | Rebase conflict: resolve the listed files in the worktree, `git -C "<Worktree>" add <files>`, run the `test` command, run the script again. Don't run `git rebase --continue` yourself. |
   | 20 | Pipeline failed: fix the cause from the log tail in the worktree, run the tests, run the script again. |
   | 30 | Push rejected: the script wrote BLOCKED. Stop. |
   | 1 | Read the message, fix the cause, run again. |
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
   - Branch <Branch> pushed · pipeline <result> · worktree removed
   ## Needs your attention
   - <anything open, risky or left undone>
   ```
   List **every** Beatrice finding from every round.
2. Set `Status: DONE` in state.md. Delete `docs/features/.active`.
3. Show the user the summary and the feature folder path.
