---
description: "One-session feature workflow for BTRC tickets: setup + native worktree, 3 parallel explorers, grill (with frontend scope questions and optional HTML mockups), spec + slice plan, ONE approval, then autonomous build per slice, tests, commit + push + CI, review rounds of 5 parallel reviewers, each checked by a verifier (up to 3), CI again after each round's fixes, optional video, finish (rebase, CI must pass), summary, worktree closed. Driven by docs/features/<ticket>/state.md and the Stop hook."
argument-hint: "<BTRC-n> \"<description>\" [base] [--no-worktree] | resume <BTRC-n>"
---

# /feature

Request: `$ARGUMENTS`

You are the orchestrator. You do every step yourself, in this one session. Your own subagents are used only for exploration (step E) and for the review round (step GB): the five reviewers (`correctness-reviewer`, `conventions-reviewer`, `tests-reviewer`, `spec-reviewer`, `playwright-reviewer`) and a `finding-verifier` for each. Up to 5 run at once.

## Rules (always)
1. `state.md` is the truth. Update it after every step, before the next one. After a compaction, read it again.
2. Run every script from the **code root** (the session's directory after `EnterWorktree`; the scripts find the feature folder from there):
   `python3 "$HOME/.claude/scripts/<name>.py" ...`
3. Code lives in the **code root**: the worktree in `Worktree:` (`.claude/worktrees/<Branch>`), or the main checkout when `Worktree mode: none`. After setup, the session works **inside** the worktree (`EnterWorktree`, step S). The feature folder lives in the worktree too, at `<worktree>/docs/features/<Ticket>/` (it is written there from the start; when the worktree is closed at the end, `worktree.py remove` copies it to the main checkout's `docs/features/<Ticket>/`); every `docs/features/<Ticket>/` path below is relative to the code root. Inside the worktree Claude Code refuses edits to the main checkout, Bash run there, and git redirected there (`git -C <main>`, `--git-dir`, `GIT_DIR`, `cd <main> && git …`); don't try them. Run commands with a subshell `(cd <folder in the worktree> && ...)` when needed, never a bare `cd`.
4. Scope: new code follows the conventions. Existing lines change only when the task needs them changed. Never rename, reformat or "fix" existing code you don't need to touch.
5. Say something works or passes only after you ran the check, and show its output. If you can't check it, say so.
6. Before approval you may ask the user anything. **After approval never ask the user anything.** Decide conservatively, write the decision in `## Log`, continue.
7. Try limits: a step fails → fix → run again. The scripts write `Status: BLOCKED: <reason>` on the 3rd failed run of the same step. For steps without a script (tests), do the same yourself. When Status is BLOCKED: tell the user the reason and stop. The VIDEO step is never a reason to block.
8. Wait for every script you start to finish before you edit state.md.
9. Don't commit during the build. You commit and push only in step C (CI) and step F (finish).
   Commits, merge requests and pushes get a **title only, no description** (no body, no trailers, no `-o merge_request.description`).
   Commit title: `<type>(<service>): <what was done>`, e.g. `feat(sunrise): add CSV export`; type is what the change is (`feat`, `fix`, `refactor`, `test`, `docs`, `chore`), the scope is the service (or `frontend`, or the lib) it changes, joined by a comma and a space when several (`feat(evermore, frontend): …`). No ticket in the commit.
   MR title: the same, followed by ` (BTRC-<n>)`. With more than one ticket, join the parts with ` & `: `feat(sunrise): add CSV export (BTRC-1234) & fix(frontend): keep the date filter (BTRC-1240)`.
10. Any `docker compose` command for this branch uses `-p <Compose project>` and the files in `Compose files:`.
11. Never add `# noqa`, `# type: ignore`, `# pylint: disable`, `eslint-disable`, `@ts-ignore`, `@ts-expect-error` or `# pragma: no cover`. Fix the code instead. The one exception: a single `# pylint: disable=duplicate-code` on its own line, directly above a function or class that deliberately mirrors its sibling. Never inside a body, docstring, call or signature, never another pylint check, and never a `# pylint: enable`.
12. Never create, rename or switch branches yourself. `worktree.py` does it, and it never creates a second branch for the same BTRC-n.
13. Tests run only on a **test database**: the one the service's test setup creates, or this branch's own stack (`-p <Compose project>`). Never on the user's own database (the one in `.env`, the default compose project, the usual local dev port). Before the first test run, find which database URL the tests will use and write it as `Test database:` in state.md; if it is the user's database, don't run the tests: point them at a test database through the test command's environment, and if none exists, write `Status: BLOCKED: no test database` (before approval: ask).
14. **Before every commit to a feature branch** (the finish commit, a pipeline fix, a quick fix, also outside `/feature`), run the changed-line check against the branch's base and fix what it lists first:
   ```
   python3 "$HOME/.claude/scripts/check_changes.py" --base <Base>
   ```
15. **Workflow feedback.** Whenever the workflow itself gets in your way, note it right away and carry on: a rule, skill, CLAUDE.md, script, hook, command or agent was wrong, unclear, contradicted another, or missing; a script failed for a reason that wasn't the code's fault, or reported something that wasn't a problem; you had to guess what a rule meant; the user corrected something a rule should have told you; a reviewer or verifier was wrong in a way its prompt could prevent; a step was slow or repeated for no good reason.
   ```
   python3 "$HOME/.claude/scripts/workflow_note.py" --kind <rule|skill|script|hook|agent|command|missing-rule|other> --source "<file or rule ID>" --what "<what happened>" --suggestion "<what to change>"
   ```
   It appends to `~/.claude/workflow-feedback/<Branch>/orchestrator.md` (outside the repo, so it outlives the worktree), with the ticket and phase. The user reviews it; never change the workflow's files yourself because of a note. Notes don't block anything and never need the user's answer.

16. **⚠ When you finish working on a branch, remove its git worktree. Always.** Leaving a worktree behind is not finished. In `/feature` this is step Z.3 (`worktree.py remove <Ticket> --done`), and nothing may come after the summary except that. Outside `/feature`, or when that script can't run: leave the worktree (`ExitWorktree`, or `cd` to the main checkout), then `git worktree remove <worktree path>`, and check `git worktree list` no longer shows it. Never `--force` over uncommitted work: commit or ask first.

## state.md format
Top fields are `Name: value` lines before the first `## `. Change one by rewriting its line.

| Field | Values |
|---|---|
| `Phase` | before approval: `SETUP`, `EXPLORE`, `GRILL`, `SPEC` · after: `BUILD`, `TESTS`, `CI`, `GATE-B`, `VIDEO`, `FINISH`, `SUMMARY` |
| `Status` | `RUNNING`, `DONE`, `BLOCKED: <reason>` |
| `Approved` | `no` until the user approves, then `yes` |
| `Session` | empty; the Stop hook writes this session's id after approval and then acts only for this session |
| `Worktree` / `Worktree mode` | written by `worktree.py`: `.claude/worktrees/<Branch>` and `worktree`, or empty and `none` |
| `Slice` / `Slices` | current slice / number of slices in plan.md |
| `Round` | review round, 1–3 |
| `Tries` | `0`, or `<STEP> <failed runs>` (e.g. `TESTS 1`) |
| `Test database` | the database URL the tests use (host, port, name; never a password), written before the first test run |
| `Commit title` / `MR title` | written in step F: `feat(evermore): add CSV export` and `feat(evermore): add CSV export (BTRC-1234)` |

`## Frontend` (filled in by the grill, step G): `- Touches frontend:`, `- Playwright reviewer:`, `- Video:`, `- HTML preview:`, `- Dev server:`, `- App URL:`, `- Backend:`, `- Login:` (yes/no or a value each).

Phases after approval: BUILD, TESTS, CI, GATE-B, VIDEO, FINISH, SUMMARY

---

## Arguments
Split `$ARGUMENTS` into words, keeping the quoted description together. The word `--no-worktree` (anywhere) is the no-worktree flag; remove it before reading the rest.
- `BTRC-<n> "<description>" [base] [--no-worktree]` → start at **S**.
- `resume BTRC-<n>` → go to **R**.

## R. Resume
1. Find the feature: `.claude/worktrees/*/docs/features/BTRC-<n>/state.md` (a worktree feature), else `docs/features/BTRC-<n>/state.md` in this checkout (a `--no-worktree` feature, a finished one whose worktree was closed, or one started before the docs lived in worktrees). If none exists: tell the user and stop.
   - If it lives in a worktree and the session isn't in that worktree yet (`claude --continue` usually returns it there by itself), call `EnterWorktree` with the worktree's absolute path.
   - An old feature folder in the main checkout with a worktree recorded: run `worktree.py create BTRC-<n>` (step S4); it moves the folder into the worktree.
2. Make sure the `docs/features/.active` next to the feature folder names `BTRC-<n>`. Never write a `.active` in the main checkout for a worktree feature.
3. If `Status` starts with `BLOCKED`: show the reason and the last 10 `## Log` lines, and stop.
4. If `Status: DONE`: show `summary.md` and stop.
5. Clear the `Session:` field (this is a new session; the Stop hook records the new id).
6. Continue at the step for `Phase` (SETUP→S, EXPLORE→E, GRILL→G, SPEC→P, BUILD→B, TESTS→T, CI→C, GATE-B→GB, VIDEO→V, FINISH→F, SUMMARY→Z). Skip work whose output file already exists and is complete.
7. Tell the user once: if the connection drops, recover with `claude --continue`, then `/feature resume BTRC-<n>`.

## S. Setup (Phase: SETUP)
1. Ticket = `BTRC-<n>` (uppercase). Title = the description.
2. Base = the `[base]` argument, else `git branch --show-current`.
3. Branch = `BTRC-<n>-<2-4 word kebab-case summary>`, e.g. `BTRC-1234-csv-export`. If a branch for this BTRC-n already exists (`git branch -a --list "*BTRC-<n>-*"`), use that name.
4. Create the code root **first**, so the feature's docs are born in it. It also keeps `.claude/worktrees/` and `docs/features/` in `.git/info/exclude`:
   - Without `--no-worktree` (always a worktree):
     ```
     python3 "$HOME/.claude/scripts/worktree.py" create <Ticket> --branch "<Branch>" --base "<Base>" --title "<Title>"
     ```
     It fetches the base and runs `git worktree add -b <Branch> .claude/worktrees/<Branch> origin/<Base>`, or reuses an existing `<Branch>`. It copies the gitignored files listed in `.worktreeinclude` (e.g. `.env`), and writes the feature folder **inside the worktree**: `<worktree>/docs/features/<Ticket>/state.md` (Ticket, Title, Branch, Base, `Repository:`, `Worktree:`, `Worktree mode: worktree`, `Phase: SETUP`) and `<worktree>/docs/features/.active`. Nothing is written in the main checkout's `docs/`. Its last line names the worktree's absolute path.
     Then call the **`EnterWorktree`** tool with that absolute path (a path under `.claude/worktrees/` needs no approval). It moves the session's directory, write access and project config (the folder `CLAUDE.md` files, settings) into the worktree. From now on, work only there; every `docs/features/<Ticket>/` path is the worktree's.
     If `EnterWorktree` isn't available in this Claude Code version: stay in the main checkout, but read and write the feature folder only with absolute paths into the worktree (`<repo root>/.claude/worktrees/<Branch>/docs/features/<Ticket>/`), never the main checkout's `docs/features/`. Tell the user once that the worktree's folder `CLAUDE.md` files may not load (read them yourself before editing a folder).
   - With `--no-worktree`: add `--no-worktree` to the same command. It switches the main checkout to `<Branch>` (creating it from `origin/<Base>` or reusing it), writes the feature folder in the main checkout's `docs/features/` (that checkout is the branch's code root) and records `Worktree mode: none`.
   Exit 2: another branch for this BTRC-n exists, or a name is missing: tell the user and stop. Exit 1: git failed (e.g. uncommitted changes in the main checkout): show the message and stop.
5. Fill `## Commands` from the root/service `CLAUDE.md` and the services' own files (`pyproject.toml`, `package.json`, CI config). Each runs in the code root through `bash -lc`. Names starting with `coverage` must print diff-cover output and pass `--include-untracked` (new files stay untracked until finish). The test command must write the coverage report the coverage command reads. Example:
   ```
   - lint: npx nx affected -t lint --base=origin/<Base>
   - typecheck: npx nx affected -t typecheck --base=origin/<Base>
   - test: npx nx affected -t test --base=origin/<Base>
   - coverage-backend: diff-cover services/evermore/coverage.xml --compare-branch=origin/<Base> --include-untracked --fail-under=100
   ```
   No test or coverage command for twilight: it has no tests.
6. `Compose files:` = the `-f` files you use to start this branch's containers (space-separated, relative to the code root), e.g. `docker-compose.yml docker-compose.dev.yml`. Start containers only with `docker compose -p <Compose project> -f <each file> up -d`.
7. Complete `docs/features/BTRC-<n>/state.md` in the code root (`worktree.py` wrote its first fields; keep them). It ends up like:
    ```markdown
    Ticket: BTRC-1234
    Title: add CSV export to entities
    Branch: BTRC-1234-csv-export
    Base: master
    Repository: /home/<you>/work/<repo>
    Worktree: .claude/worktrees/BTRC-1234-csv-export
    Worktree mode: worktree
    Compose project: btrc-1234
    Compose files: docker-compose.yml
    Test database:
    Commit title:
    MR title:
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

    ## Frontend

    ## Log
    - <DD/MM/YYYY HH:MM> setup done on <Base>
    ```
    - `Compose project` = `btrc-<n>` (lowercase).
    - Leave `Slices:` and `Session:` empty; later steps fill them. Set `Phase: EXPLORE` last.
8. In the code root, show the output of `git status` and `git worktree list`.

## E. Explore (Phase: EXPLORE)
1. Start 3 `explorer` agents **in one message** (parallel). Same prompt for each, only `n` differs:
   ```
   Feature: <Ticket> "<Title>"
   Feature directory: <absolute code root>/docs/features/<Ticket>
   Code root: <absolute code root>
   Your number n: <1|2|3>
   Explore the whole scope of this feature. Write only explore/explorer-<n>.md.
   ```
2. Wait for all 3. Check that `explore/explorer-1.md`, `-2.md`, `-3.md` exist. If one is missing, run that one again once; if it still fails, continue with the others and log it.
3. Merge them yourself. Same item from several explorers = one item. Mark each item with how many found it: `(3/3)`, `(2/3)`, `(1/3)`. Never drop an item because only one explorer found it.
   - `context.md`: `# Context: <feature>`, then the sections Services touched, Files likely to change, Similar existing features, Integration points, Tooling (incl. commands), Risks.
   - `patterns.md`: `# Patterns: <feature>`, then `## P-1 <name>` … (Reference, Shape, Tested by, mark), then `## Inconsistencies` with `I-1` ….
4. Check every `(1/3)` item in the code now: open the cited file. Change the mark to `(1/3, checked)` or `(1/3, wrong: <why>)`. Rely only on checked items.
5. `patterns.md` must have at least one `P-n`. If not, explore that part yourself.
6. If the explorers found better commands than `## Commands`, update them. Write `- Touches frontend: yes` or `no` under `## Frontend` (yes when any file likely to change is under the frontend). Set `Phase: GRILL`.

## G. Grill (Phase: GRILL)
1. Load the `grill-with-docs` skill and follow it fully with the user. Input: the description, `context.md`, `patterns.md`.
2. **Frontend scope** (only when `- Touches frontend: yes`, also when the backend is touched too; then always): the first batch **asks** the user the frontend questions of the grill skill (§ Frontend scope), with `AskUserQuestion`: whether to dispatch the Playwright reviewer in the review rounds, whether they want a Playwright video at the end, and an HTML preview of the design with options. Each is recommended yes, but write only what the user answered, never a default; and, if the reviewer or the video is yes, how to run the app (dev server, URL, backend mocked or local docker stack, login). Write the answers under `## Frontend`. Test credentials come only from the project's seed/fixture files (record the file path) or from the user; never put a password in state.md.
3. **HTML preview** (only when `- HTML preview: yes`): before the spec, load the `html-mockups` skill and write `docs/features/<Ticket>/mockups/<screen>.html` for each new or changed screen, dialog or component, with **2–3 design options** each for the user to choose from (plain HTML/CSS, no CDN, light/dark toggle, RTL toggle, empty/loading/error states). Tell the user the paths and ask for changes in the next grill round. Repeat until they approve the mockups.
4. Every inconsistency `I-n` must end as a decision.
6. It ends when `grill-notes.md` has no open or assumed unknowns and the user confirmed the readback. Set `Phase: SPEC`.

## P. Spec, plan, approval (Phase: SPEC)
1. Load the `write-spec` skill. Write `spec.md` and `plan.md` yourself (no subagent), from its templates. The first line of spec.md is `# Spec: <feature name>` (it becomes the commit title). When mockups were approved, the spec links each one (`mockups/<screen>.html`) from the requirement it shows.
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
4. Check `## Commands`, `## Frontend` and `Compose files` in state.md are final.
5. Approval is your **last question**. Show: goal, number of REQs/ECs/slices, every `NEW` pattern, the riskiest decision, the paths of spec.md and plan.md (and the mockups). Ask with `AskUserQuestion`: "Approve the spec and plan?" → "Approve and start (Recommended)" / "I have changes". On changes: edit, ask again.
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
   python3 "$HOME/.claude/scripts/check_changes.py" --slice <Ticket> <Slice>
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
   | `test_entity_by_id_missing_id_raises_not_found_error` | Reading an entity id that doesn't exist | Raises `NotFoundError` with "Entity 7 was not found." | `services/evermore/tests/entities/test_read_entity.py` |
   ```
   Test name = the exact pytest function name / `it(...)` / `test(...)` string. File = path relative to the **repo root**. Cover every REQ, EC and new code path, except in twilight (no tests there). No `|` inside a cell.
2. Write the tests. Load before each kind: `pytest-conventions` + `backend-test-infra` (backend), `vitest-conventions` (frontend), `browser-test-conventions` (Playwright). A service's `tests/CLAUDE.md` wins over the skills.
3. The test-plan hook blocks any test whose exact name isn't in the first column. Add the row first, then write the test.
4. Test helper files (conftest, environment builders, factories, MSW handlers) that aren't in the File column: add them to the last slice's `Files:` in plan.md and log why.
5. Check `Test database:` (rule 13) before the first run. Then run the `test` command and every `coverage*` command from `## Commands`, in the code root.
   - Failing test that shows a real bug → fix the code, log it.
   - Changed lines without coverage → add a planned test. Only if a line truly can't be tested, add `- path:lines: reason` under `## Coverage exemptions`, with the full repo-relative path (e.g. `- services/evermore/app/x.py:40-42: unreachable after the validator`).
6. Limit: after a failed run set `Tries: TESTS <failed runs>`. On the 3rd failed run write `Status: BLOCKED: tests fail after 2 fixes` and stop.
7. All green: set `Tries: 0`, `Phase: CI`.

## C. CI (Phase: CI)
The pipeline is the gate: lint, typecheck, tests and coverage run in CI, not in a local script. You commit, push and read the result.
1. First time only: write `Commit title:` and `MR title:` in state.md (rule 9), e.g. `Commit title: feat(evermore): add CSV export to entities`.
2. Run the changed-line check (rule 14) and fix what it lists.
3. Commit, title only: `git add -A`, `git commit -m "<title>"`. The first commit uses `Commit title:`; later ones say what they change in the same format (`fix(evermore): handle an empty export`).
4. Push: `git push --force-with-lease origin HEAD:refs/heads/<Branch>` (the first push creates the branch). Rejected because someone else pushed: write `Status: BLOCKED: someone else pushed to <Branch>` and stop.
5. Watch the pipeline of the commit you pushed: `glab ci status --branch <Branch>` every minute (Bash `sleep 60` between runs, up to 45 minutes).
   - **Passed**: write `- ci: passed (<short commit>) round <Round>` in `## Log`, set `Tries: 0`. Then `Phase: GATE-B`; or, when `review/triage.md` already has `## Round 3` (the last round's fixes just passed), `Phase: VIDEO` (when `- Video: yes`) or `Phase: FINISH`.
   - **Failed**: `glab ci trace <job> --branch <Branch>` for the failing job, fix the cause, run the tests locally, and go back to step 2. Set `Tries: CI <failed runs>`; on the 3rd failed pipeline write `Status: BLOCKED: pipeline fails after 2 fixes` and stop.
   - Manual, blocked or canceled, or still running after 45 minutes: write `Status: BLOCKED: pipeline <state>` and stop.

## GB. Gate B, the review round (Phase: GATE-B), round = `Round`
Five reviewers look at the branch, each for one kind of problem; a verifier then checks every finding. You fix what is real. Up to 3 rounds.
`<scripts>` below is `$HOME/.claude/scripts`.

1. If `python3 "<scripts>/review_round.py" triage-check <Ticket> <Round>` passes, this round is triaged: skip to step 6.
2. **Reviewers.** `python3 "<scripts>/review_round.py" expected <Ticket> <Round>` lists them: `correctness`, `conventions`, `tests`, `spec`, and `playwright` when `- Playwright reviewer: yes`. In **one message**, start the agent `<source>-reviewer` for every one whose `review/<source>-<Round>.md` is missing or has no `Done:` line, all at once (up to 5). Give each: feature directory, code root, `Base`, round. The `playwright-reviewer` also gets the `## Frontend` answers (plus the test password if the user typed it; never write it to a file).
   Each writes `review/<source>-<Round>.md`: per finding, `## <where> | <rule>` (a `file:line`, or for playwright a place in the app) and the problem, ending with `Done: <k> finding(s)`. Reviewers write no ids. Each prompt says what that reviewer does not judge, so they don't overlap. Reviewers focus on what the branch changed, but may report a problem in code the branch uses or affects (conventions only on lines the branch wrote).
3. **As each reviewer finishes** (don't wait for the others), check and store its file before anything changes:
   ```
   python3 "<scripts>/review_round.py" capture <Ticket> <Round> --source <source>
   ```
   It numbers the findings (`K` correctness, `C` conventions, `T` tests, `S` spec, `P` playwright, e.g. `K1-3`, written into the file). Exit 1 (missing file, no `Done:` line, a count that doesn't match, a header that isn't a finding): start that reviewer again. 3 failures in a row block the feature. Exit 0: when it found something, start a **`finding-verifier`** for that source right away, with feature directory, code root, `Base`, round and the source. It writes `review/verify-<source>-<Round>.md`: `## <id> | sure|unsure|invalid` per finding, with evidence. When it finishes, run
   ```
   python3 "<scripts>/review_round.py" verify-check <Ticket> <Round> --source <source>
   ```
   Exit 1: start that verifier again (3 failures block). A source with `Done: 0 finding(s)` needs no verifier.
4. **Triage**, once every expected source is captured and verified. Don't fix anything yet. Append to `review/triage.md` one row per finding (Verdict = the verifier's word; a finding marked "Dismissed in round N, because …" keeps that decision unless the line changed):
   ```markdown
   ## Round <Round>
   | # | Source | Verdict | File:line | Rule | Finding | Decision | Reason |
   |---|---|---|---|---|---|---|---|
   | K1-1 | correctness | sure | services/evermore/app/x.py:40 | EC-2 | missing None check | fix | |
   | C1-2 | conventions | invalid | services/evermore/app/x.py:52 | PY-24 | call not exploded | dismiss | verifier: the call fits on one line under 80 chars |
   | T1-1 | tests | unsure | services/evermore/tests/x/test_y.py:12 | TS-29 | reads with the reader | fix | |
   ```
   - `sure` → Decision **fix**. Always.
   - `invalid` → Decision **dismiss**, Reason = the verifier's evidence. Never fix it.
   - `unsure` → open the code and decide yourself: `fix`, or `dismiss` with a Reason pointing to a line, a rule or a screenshot.
   No `|` inside a cell. Then run `python3 "<scripts>/review_round.py" triage-check <Ticket> <Round>`: exit 1 lists what's missing or doesn't follow the verdict; fix the table and run it again.
5. **Fix** every `fix` row, one after another, then run the checks once.
6. Next:
   - No `fix` rows this round → set `Phase: VIDEO` when `- Video: yes`, else `Phase: FINISH`.
   - `fix` rows and `Round` < 3 → fix them all, then set `Round: <Round+1>` and `Phase: CI` (the fixes are committed, pushed and checked there).
   - `fix` rows and `Round` = 3 → fix them, keep `Round: 3`, set `Phase: CI`. When CI passes it goes on to `Phase: VIDEO` or `Phase: FINISH`. Leftovers go into the summary.
   A dropped connection mid-round: start again at step 1; reviewers and verifiers whose files are complete aren't run again.

## V. Video (Phase: VIDEO)
1. Record one Playwright run with `recordVideo` that walks the new behaviour step by step (every frontend REQ in order), with `page.waitForTimeout(800)` pauses so it can be followed. Start the app as in `## Frontend`, use the repo's own Playwright (`npx playwright`, browsers preinstalled; never download), and keep the script in `docs/features/<Ticket>/playwright/video.cjs` (never in the repo's test folders). The `playwright-reviewer` agent's file layout is the model.
2. Save the video as `docs/features/<Ticket>/video/<Ticket>.webm` (rename Playwright's file). Stop the app.
3. If recording fails: write why in `## Log` and later in summary.md, and continue. Never write BLOCKED for this.
4. Set `Phase: FINISH`.

## F. Finish (Phase: FINISH)
**The feature is finished only when all four are true:** the branch is rebased on the latest base, the pipeline of the pushed commit **passed**, every container of this branch is closed, and the worktree is closed (step Z). Not one of them may be skipped, assumed or left for the user. `worktree.py remove --done` checks all of them and refuses to set `Status: DONE` until they hold.
You do this step yourself, in the code root (the worktree), one command at a time. Record each finished step as a line under `## Finish` in state.md, exactly as written below, so a resume skips what's done.
1. Check `Commit title:` and `MR title:` in state.md (written in step C) still describe the whole branch; fix them if not.
2. Check: `git branch --show-current` is `<Branch>`, never `<Base>`. If not, write `Status: BLOCKED: wrong branch checked out` and stop.
3. Commit anything still uncommitted (usually nothing: step C committed the work). Run the changed-line check (rule 14) first, then, title only: `git add -A`, then `git commit -m "<Commit title>"` (no `-m` body, no trailers). `docs/features/` is git-ignored, so it isn't committed.
4. Rebase on the base: `git fetch origin`, then `git pull --rebase origin <Base>`.
   - Conflict: resolve each listed file (no `<<<<<<<` / `>>>>>>>` left), `git add <files>`, run the `test` command, then `git -c core.editor=true rebase --continue`. Repeat until the rebase is done.
   - Check it: `git merge-base --is-ancestor origin/<Base> HEAD` succeeds. Then write `- rebase: done`.
5. Push: `git push --force-with-lease origin HEAD:refs/heads/<Branch>`.
   - Rejected because someone else pushed to the branch: write `Status: BLOCKED: someone else pushed to <Branch>` and stop. Never force over it.
6. CI must pass: run `glab ci status --branch <Branch>` every minute (Bash `sleep 60` between runs, up to 45 minutes) until the pipeline of the pushed commit finishes.
   - Passed: write `- pipeline: passed (<short commit>)` and go on.
   - Failed: `glab ci trace <job> --branch <Branch>` for the failing job, fix the cause, run the changed-line check (rule 14) and the tests, commit with the same title style (`fix(<service>): <what was fixed>`), remove the `- rebase:` and `- pipeline:` lines, and go back to step 4. A pipeline that passed for an older commit doesn't count.
   - Manual, blocked or canceled, or still running after 45 minutes: write `Status: BLOCKED: pipeline <state>` and stop.
   Never write the summary on a failed or unfinished pipeline.
7. Close **every** container of this branch: `docker compose -p <Compose project> -f <each Compose file> down --remove-orphans` (volumes are kept), and stop anything else you started for it (a dev server, a Playwright browser). Check: `docker ps --filter label=com.docker.compose.project=<Compose project>` lists nothing. Then write `- containers: closed`.
8. With `Worktree mode: none`: update the base in the main checkout (`git fetch origin <Base>:<Base>`).
9. Set `Phase: SUMMARY`. The worktree is closed in step Z; until then the feature isn't finished.

## Z. Summary (Phase: SUMMARY)
1. Write `docs/features/<Ticket>/summary.md` in the code root:
   ```markdown
   # Summary: <Ticket> <feature>
   ## Built
   - REQ-1 … (files)
   ## Deviations
   - DEV-n … (from ## Log)
   ## Tests
   - <n> tests · changed-line coverage: <result> · exemptions: <list or none>
   ## Reviews
   | Round | # | Source | Verdict | File:line | Finding | Outcome (fixed / dismissed: reason / left open) |
   ## Video
   - docs/features/<Ticket>/video/<Ticket>.webm (or: not recorded, because …; or: not requested)
   ## Finish
   - Branch <Branch> pushed · pipeline passed · containers stopped · worktree closed (or: main checkout, base updated)
   - Commit: `<Commit title>` · MR title: `<MR title>`
   - Feature folder kept at <main checkout>/docs/features/<Ticket>/
   ## Needs your attention
   - <anything open, risky or left undone>
   ```
   List **every** finding of every source from every round.
2. Show the user the summary.
3. **⚠ Remove the git worktree (rule 16). Never skip this, never leave it for the user.** It's the last of the four conditions and the only way to `Status: DONE`; the Stop hook keeps you going until it's set:
   - Worktree feature: call **`ExitWorktree`** with action `keep` (the script removes it), then from the main checkout run
     ```
     python3 "$HOME/.claude/scripts/worktree.py" remove <Ticket> --done
     ```
     It first checks the other three: the `## Finish` lines `- rebase: done`, `- pipeline: passed`, `- containers: closed`, that `origin/<Branch>` is the local branch and sits on the latest `origin/<Base>`, and that no container of `<Compose project>` runs. Any of them failing: exit 1 with the list; go back to step F, fix it, and run it again. Then it copies the feature folder to `<main checkout>/docs/features/<Ticket>/`, runs `git worktree remove` (the branch stays) and sets `Status: DONE` in the copy. If `ExitWorktree` isn't available, run the same command from the worktree, and run nothing in it afterwards.
     Exit 1 (uncommitted files): show `git status` of the worktree, and stop with that message.
   - `Worktree mode: none`: run the same command; it only sets `Status: DONE` and deletes `.active`.
4. Check `git worktree list` (from the main checkout) no longer shows `<Worktree>`. Then tell the user the worktree was removed, the feature folder path and the MR title.
