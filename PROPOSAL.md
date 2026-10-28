# Workflow proposal: midnight-api on Qwen 3.8 27B

Status: v6, built · 28/10/2026 (v5 decisions, plus the review fixes and the Ubuntu user-level install)

## 0. Decisions so far

| # | Topic | Decision |
|---|---|---|
| 1 | Dates | `DD/MM/YYYY`, full years. **Done**: python-conventions (both copies) and `check_python_conventions.py` now require it, with a test for a 2-digit year. |
| 2 | String constants | Strings of 5+ words become constants. Except where reading the string in place matters: error messages, `raise`, settings, and similar. Short strings stay inline. |
| 3 | `get_` prefix | New functions never start with `get_` (`entity_by_id`). Existing names (`get_session`, `get_and_inc`) stay as they are. |
| 4 | Suppressions | None allowed: no `# noqa`, `# type: ignore`, `# pylint: disable`, `eslint-disable`. A script fails on any new one. |
| 5 | Tests source | `services/evermore/tests/CLAUDE.md` defines evermore's test model. The general pytest skill drops its `db_session` and factory examples. |
| 6 | Force push | `--force-with-lease=<branch>:<last commit the script pushed>`: it refuses if someone else pushed to the branch since then (a plain `--force-with-lease` after `git fetch` would protect nothing). |
| 7 | Who drives | One orchestrator session does everything, start to finish. `claude -p` is used only to run Beatrice. |
| 8 | Subagents | Only for exploration: 3 in parallel, each exploring the whole scope. The orchestrator plans, implements, writes tests and fixes by itself. |
| 9 | Test plan | Exactly four columns: test name, what it checks, expected result, file. |
| 10 | Beatrice | Two `claude -p` runs in parallel per round, so each can use its own subagents. Up to 5 rounds. |
| 11 | Install | Ubuntu, user level: `install.sh` copies commands, agents and skills into `~/.claude/`, the scripts into `~/.claude/midnight-workflow/scripts/`, and merges the hooks into `~/.claude/settings.json`. Not a plugin, not Windows. |

Problems this targets:

| # | Problem | Fix |
|---|---|---|
| P1 | Claude changes legacy code in touched files | The edit hook only reports changed lines, plus a scope rule and a scope check (§2.4) |
| P2 | Manual fix → `/beatrice-code-review` → fix cycle | Beatrice runs **inside** the loop as the last step (§2.5) |
| P3 | Grill questions lose context | Every question first quotes your words for what it's about (§2.3) |
| P4 | Two branches for one BTRC-n | A hook blocks it (§2.6) |
| P5 | "connection closed mid-response" stops the run | Everything is on disk; one command resumes from the last step (§2.2) |
| P6 | End-of-branch chores | One finish script (§2.7) |

Marked **(unverified)** = needs checking in your offline environment.

---

## 1. The workflow, in plain words

One Claude session, the **orchestrator**, runs the whole feature. You talk to it until you approve the spec; after that it doesn't ask you anything. Two things keep a 27B model on track through a long run:
- **`state.md`**: every step writes where it is. After a compaction or a disconnect, the orchestrator reads it and continues.
- **A Stop hook** (`next_step.py`): when the orchestrator tries to end its turn before the feature is `DONE` or `BLOCKED`, the hook refuses and tells it the exact next step, read from `state.md`. So the phase order lives in a script, not in the model's memory, but it's still one session.

You type: `/feature BTRC-1234 "add CSV export to entities"`

### Before your approval (you answer questions)
1. **Setup.** The orchestrator records the ticket, the branch name (`BTRC-1234-csv-export`), the base branch (the one you're on now, or the one you name), and creates the worktree at `<repo>/.worktrees/BTRC-1234` (inside the project, so edits there need no extra permission; `.worktrees/` is in `.git/info/exclude`). All of it goes into `docs/features/BTRC-1234/state.md`.
2. **Explore.** Three explorer subagents run in parallel with the **same** task: explore the whole scope of the feature. Each writes its own `explore/explorer-<n>.md`. The orchestrator merges them into `context.md` (files involved) and `patterns.md` (how similar things are done today), marking each item with how many explorers found it (`3/3`, `2/3`, `1/3`). Items only one explorer found are the ones the others missed, so they're kept, and the orchestrator checks them in the code before relying on them.
3. **Grill.** The orchestrator interviews you (§2.3). Every question starts by quoting your words for the requirement it's about.
4. **Spec and plan.** The orchestrator writes them itself, no subagent: `spec.md` (what will be built) and `plan.md` (tasks grouped into 2–4 slices, each listing the files it may touch).
5. **You approve.** The last question you get.

### After your approval (no questions)
6. **Build, slice by slice.** The orchestrator implements a slice, then runs `python3 "$HOME/.claude/midnight-workflow/scripts/check_slice.py" BTRC-1234 <slice>` (lint, types and scope, changed lines only). Failures come back as an exact `file:line` list; it fixes them (up to 2 tries) and moves on.
7. **Tests.** It writes `test-plan.md` in the four-column format (§2.8), then the tests. A hook blocks any test that isn't in the plan. It runs the tests and changed-line coverage and fixes failures (up to 2 tries).
8. **Gate A.** `python3 "$HOME/.claude/midnight-workflow/scripts/gate_a.py" BTRC-1234` checks everything Beatrice would reject before reading a line: lint, typecheck, all tests, 100% changed-line coverage (or an exemption with a reason in `state.md`), scope, no suppressions. Failures → fix (up to 2 tries).
9. **Gate B, Beatrice.** The orchestrator runs `python3 "$HOME/.claude/midnight-workflow/scripts/run_beatrice.py" BTRC-1234 <round>`, which starts your team leader's command unchanged in **two `claude -p` sessions in parallel** (§2.5) and merges their findings into `review/beatrice-<round>.md`. The orchestrator marks each finding `fix` or `dismiss: <reason pointing to a line or a rule>`, fixes, re-runs Gate A, and starts the next round. **Up to 5 rounds.**
10. **Finish.** The orchestrator runs `python3 "$HOME/.claude/midnight-workflow/scripts/finish_branch.py" BTRC-1234` (§2.7): commit, pull --rebase on the base, push, wait for the pipeline, stop the branch's containers, remove the worktree, pull the base in the main checkout. On a conflict or a red pipeline the script stops with a clear code, the orchestrator fixes and runs it again (up to 2 times).
11. **Summary.** `summary.md`: what was built, every Beatrice finding and what happened to it, and anything left for you.

If a step hits its try limit, the orchestrator writes `BLOCKED: <reason>` in `state.md` and stops; the Stop hook lets it.

### What you see
```
You:            /feature BTRC-1234 "..."  →  answer questions  →  approve
Orchestrator:   slices → tests → Gate A → Beatrice ×≤5 → finish script → summary.md
If it dropped:  claude --continue, then /feature resume BTRC-1234
```

### How it differs from what you run today
| Today | Proposed |
|---|---|
| The orchestrator remembers the phase order from a long prompt | `state.md` + a Stop hook tell it the next step |
| One explorer | 3 in parallel, same task, results merged |
| 4 home-made reviewers, then you run Beatrice by hand | Scripts (Gate A), then Beatrice ×2 in the loop, ≤5 rounds |
| The edit hook reports problems in the whole file | Only in the lines you changed |
| Git, pipeline and docker at the end by hand | One finish script |
| Test plan with layers, IDs, coverage map | Four columns |

---

## 2. Details

### 2.1 Files
`docs/features/BTRC-1234/` (git-ignored through `.git/info/exclude`): `state.md`, `explore/explorer-<n>.md`, `context.md`, `patterns.md`, `grill-notes.md`, `spec.md`, `plan.md`, `test-plan.md`, `review/` (Beatrice output `beatrice-<n>.md` + `beatrice-<n>.json`, `triage.md`, `dismissed.json`), `beatrice-log.md`, `summary.md`, and the scripts' `.running.json` / `.stop-hook.json`. Plus `docs/features/.active` (the hooks use it). The worktree is `<repo>/.worktrees/BTRC-1234`.

### 2.2 Why one orchestrator and not `claude -p`
You're right that, for context, a `claude -p` call and a subagent are nearly the same: each starts fresh and returns a result. The difference is **who decides what runs next**:

| | Orchestrator + subagents | Script + `claude -p` |
|---|---|---|
| Decides the next step | The model (here: helped by the Stop hook) | Code |
| Context | Grows over the run; auto-compaction trims it | Fresh every call |
| After a disconnect | You resume with one command | The script retries by itself |
| Setup | Hooks you already know | Permissions flags, timeouts, quoting |
| Speed on a local model | No extra start-up per step | A new process and prompt load per step |

With the Stop hook and `state.md`, the orchestrator gets most of what the script would give. What you give up: a disconnect needs you to resume. That's one command, `claude --continue` then `/feature resume BTRC-1234`, and nothing is lost, because every step writes to `state.md` before moving on.

The Stop hook, `scripts/hooks/next_step.py` (your `WORKFLOW_IMPROVEMENTS.md` already has a draft of the same idea):
- No active feature, or `state.md` says `DONE` / `BLOCKED` → it lets the orchestrator stop.
- It acts only for the orchestrator's session: the first stop after approval records its `session_id` as `Session:` in `state.md`, and stops of any other `claude` session in the same repo are let through.
- While a long script runs (`run_beatrice.py`, `gate_a.py`, `finish_branch.py` hold `.running.json`), it lets the orchestrator wait.
- Otherwise it blocks the stop and returns the next step from a fixed table, e.g. `Phase: GATE-B, round 2 → run run_beatrice.py BTRC-1234 2, then triage review/beatrice-2.md`. The table matches `/feature` word for word, and a test checks it.
- A circuit breaker: after 8 blocks without `state.md` changing, it lets the orchestrator stop and writes `BLOCKED: no progress`. The count starts again whenever a stop is allowed.
- Before your approval, it never blocks, so the grill stays a normal conversation.
- It does nothing in the Beatrice `claude -p` sessions: `run_beatrice.py` starts them with `MIDNIGHT_ROLE=reviewer`, and every workflow hook exits right away when it sees that.

About the disconnects themselves: I haven't checked the cause in your setup. It's usually a proxy or server timeout cutting a long streamed answer **(unverified)**. If they follow long answers, try a lower `CLAUDE_CODE_MAX_OUTPUT_TOKENS` and a higher `API_TIMEOUT_MS` in `settings.json` → `env`.

Your local server handles parallel requests, so the 3 explorers and the 2 Beatrice runs really run at the same time.

### 2.3 Grill
**Yes, it's based on Matt Pocock's `grill-me` / `grill-with-docs`** (from memory of his skills repo; check against your copy). Kept from his version:
- Interview until there's a shared understanding, walking the decision tree and settling decisions that others depend on first.
- Every question comes with a recommended answer.
- Never ask what the code can answer; look it up instead.
- (`grill-with-docs`) Challenge terms against the domain glossary `docs/CONTEXT.md`, and record new terms and lasting decisions in the glossary and in ADRs as you go.

Changed or added for your workflow:
- **Batches of up to 4 related questions** instead of one at a time, which is faster on a slow model. Questions that depend on each other never go in the same batch.
- **Your words, quoted.** `grill-notes.md` keeps your requirements verbatim, and every question opens with the one it's about:
  > **About R-2** ("if the export takes long, don't block the page"): should the page poll for the result, or should you get a snackbar when it's ready?

  When there's no R-n, it quotes the code fact instead ("`patterns.md` P-3: entities export uses a Temporal workflow").
- **A coverage checklist** (behavior, data, API, proxy, errors, edge cases, UI states, git, …) and `Covered: … · Left: …` after each round, so nothing is skipped.
- **An unknowns list**: every assumption must become a decision or a question before the spec.
- **A readback** at the end: 5–8 bullets of what will and won't be built, which you confirm.

### 2.4 Legacy code (P1)
The likely cause, which I checked by reading the code: `scripts/hooks/post_edit_checks.py` runs the convention checker and ruff on the **whole file** after each edit, and answers `Fix every item below before continuing`. So every legacy file Claude touches comes back with a list of old violations to fix.
1. The hook keeps only problems touching changed lines (`git diff -U0 <merge-base> -- <file>`; the whole file if it's new). Same for ruff and eslint. A `get_` name that existed in the base version isn't new. Because the hooks are user-level, it acts only while an approved feature runs (or with `MIDNIGHT_CHECKS=1`).
2. Root CLAUDE.md scope rule (draft in §4.2).
3. Scope check (in `check_slice.py` and Gate A): fails on files outside the slice's allowed list, and lists changed **existing** lines as `file:line` so the orchestrator can redo them. Nothing is reverted automatically.
4. Each convention skill starts with: "Applies to code you write or change. Never to unchanged lines."
5. What scripts can't tell apart (a needed change vs. a style rewrite of the same line) is left to rule 2 and to Beatrice's "is anything in the diff not what we asked for" check.

### 2.5 Beatrice (P2)
**How the command runs: two `claude -p` sessions per round.** A subagent can't start subagents of its own, so if Beatrice ran as a subagent, any subagents her command uses wouldn't work. A `claude -p` session is a full session, so it can. The orchestrator runs one command, in the background (a run can take longer than a normal command's time limit), and is told when it finishes:
```
python3 "$HOME/.claude/midnight-workflow/scripts/run_beatrice.py" BTRC-1234 <round>
```
The script:
1. Starts two sessions at the same time, in the worktree, with `MIDNIGHT_ROLE=reviewer` set:
   ```
   claude -p "/beatrice-code-review <base>" --output-format json --permission-mode default \
     --allowedTools "Read,Grep,Glob,Agent,Bash(git diff:*),Bash(git log:*),Bash(git show:*),Bash(glab mr view:*),Bash(glab mr diff:*),Bash(npx nx lint:*),Bash(npx nx typecheck:*),Bash(npx nx test:*)" \
     --disallowedTools "Edit,Write,MultiEdit,NotebookEdit" \
     --append-system-prompt "<ask for a beatrice-findings block at the end>"
   ```
   Read-only: no Edit or Write, and only read-only `glab mr` and `nx` targets (`glab mr:*` would allow merge/approve/close). Adjust the Bash list to the commands Beatrice actually runs. The command file stays unchanged; the findings block comes from the appended system prompt, with a free-form parser as fallback.
2. Gives each one a timeout (30 min; the whole process group is killed). A run counts only when the JSON result isn't an error and has an answer; if `claude -p` doesn't know the slash command, the retry sends the command file's text. If one fails or the connection drops, it re-runs that one once. If it fails again, the round continues with the other one's findings, and `state.md` notes it.
3. Merges both outputs into `review/beatrice-<round>.md`: findings for the same file, rule and line become one, marked `2/2`; the rest are marked `1/2`. Both kinds go to triage; nothing is dropped because only one run found it. `beatrice-<round>.json` keeps the same findings with each flagged line's text as it was during the review.

Two things to check in your version **(unverified)**: that `claude -p` runs a custom slash command (if not, the script passes the text of the command file as the prompt; it's the same instructions), and the exact `--allowedTools` syntax. The command file itself stays untouched.

The loop:
- **Fewer findings to start with:** Beatrice's judgement-call list is copied into the checklists the orchestrator uses while building, and Gate A enforces what Beatrice requires (green pipeline, 100% coverage or a reason, no suppressions).
- **Triage:** each finding gets `fix` or `dismiss: <reason pointing to a line or a rule>` in `review/triage.md`.
- **No ping-pong:** `gate_a.py` also keeps a list of dismissed findings keyed by `file + rule + the flagged line's text`, taken from `beatrice-<round>.json` (so fixes that shift lines don't change it). When the same finding comes back, the orchestrator is told "dismissed in round N, because …". A new violation on another line is still new.
- **5 rounds max.** After round 5's fixes, Gate A moves straight to FINISH. Leftovers go into `summary.md` with reasons. Two runs per round catch more of what a single run of Beatrice would raise when you run it yourself, but it's an LLM, so it can't be ruled out.
- **Learning:** round-1 findings are appended to `beatrice-log.md`. After 3–5 features, recurring ones become checklist lines or checker rules.

### 2.6 One branch per BTRC (P4)
`guard_branch.py`, a hook that runs before every Bash command. When a command creates or renames a branch (`checkout -b/-B/--orphan`, `switch -c/-C/--create`, `branch <name>`, `branch -m`, `worktree add` with or without `-b`, `push <remote> <x>:<name>` but not deletes; also inside `bash -c`, after `VAR=`/`sudo`, in subshells), it runs `git fetch --prune` (15 s, no prompts; on failure it still checks the refs it has) and blocks the command if a branch with the same `BTRC-<n>` already exists under another name. No exceptions: if you really need a second one, you create it yourself.

### 2.7 Finish: how the commands run (P6)
The orchestrator runs one command: `python3 "$HOME/.claude/midnight-workflow/scripts/finish_branch.py" BTRC-1234`. The script reads the branch, base, worktree, container project and compose files from `state.md`, checks the worktree is on the branch and the branch isn't the base, and runs, in order:
```
git add -A                                       # after a conflict instead: refuse while files are unmerged or hold
git commit -m "BTRC-1234: <title from spec.md>"  #   <<<<<<< / >>>>>>>, then git add -u + git rebase --continue
git fetch origin                                # refuse (30) if origin/<branch> moved to a commit the script didn't push
git pull --rebase origin <base>
git push --force-with-lease=refs/heads/<branch>:<last pushed commit> origin HEAD:refs/heads/<branch>
glab ci status --branch <branch>                # polled every 30 s until it passes or fails, max 45 min
docker compose -p btrc-1234 -f <files> down --remove-orphans   # same project and files setup used
git worktree remove <worktree path>
git pull --ff-only origin <base>                # in the main checkout (or fetch origin <base>:<base>)
```
It records each finished step in `state.md`, so running it again skips what's done. It stops with an exit code the orchestrator acts on:

| Code | Meaning | Orchestrator does |
|---|---|---|
| 0 | Done | Writes the summary |
| 10 | Rebase conflict (files listed) | Resolves, runs the tests, runs the script again |
| 20 | Pipeline failed (failing job's log tail) | Fixes, runs the script again |
| 30 | Push rejected | `BLOCKED`: someone else pushed; you decide |

Exit 1 is any other error (e.g. glab failing, a pipeline waiting for a manual job) and 2 a setup error (wrong branch, Branch = Base, another run still going). After 2 re-runs for the same code it writes `BLOCKED`. Check the `glab ci status` flags in your glab version **(unverified)**. Add `-v` to `docker compose down` only if the branch's volumes hold nothing you need.

### 2.8 Test plan format
`test-plan.md` is one table, nothing else:

| Test name | What it checks | Expected result | File |
|---|---|---|---|
| `test_entity_by_id_missing_id_raises_entity_not_found_error` | Reading an entity id that doesn't exist | Raises `EntityNotFoundError` with "Entity 7 was not found." | `tests/entities/test_read_entity.py` |

Coverage exemptions and test results, which used to live in the test plan, go to `state.md`. The hook that blocks unplanned tests matches test names anywhere in the file, so it works with this format unchanged (checked in `guard_test_plan.py`).

---

## 3. Superpowers vs. feature-dev

- **superpowers** (github.com/obra/superpowers): brainstorm → fine-grained plan (tasks with exact files, often the code) → `subagent-driven-development`: a fresh subagent per task, then a reviewer with a spec verdict and a quality verdict, with up to 5 fix rounds. It also has strict TDD (code written before its test is deleted), worktrees, a "verify before claiming done" skill, and a finish-branch skill.
- **feature-dev** (github.com/anthropics/claude-plugins-official, `plugins/feature-dev`): one command, 7 phases: discovery, exploration agents, clarifying questions, architecture options, implementation, review agents that only report findings with confidence ≥ 80, summary. It stops about 5 times for you, including after the review.

**"superpowers planning + feature-dev executing" is backwards.** feature-dev is good at exploring and filtering review noise; its implementation step is just the agent implementing. superpowers is good at execution. Neither fits as-is: feature-dev keeps asking after implementation, and strict TDD fights evermore's inventory environment (a test's data is environment setup, not part of the test). What this proposal takes from them:
1. Small pieces of work, checked right after. Per **slice**, by the orchestrator itself with a script check, not a subagent per task: that's too slow on a local model. Fresh context is kept for where it matters most: exploration and Beatrice.
2. "Verify before claiming": your "state stuff only after checking" rule.
3. The confidence ≥ 80 filter, for your own extra reviewers only, **never** for Beatrice.
4. A finish-branch step, rewritten for your git, docker and worktree rules.

Also looked at: **Ralph loop** ("don't stop until done, state on disk": the idea behind the Stop hook), **GitHub Spec Kit** (good spec/plan templates, but too many approval gates), **BMAD** (too many agents and documents for a 27B model). Whether this flow beats your current one is something the pilot (§5) has to show.

---

## 4. Skills, hooks and CLAUDE.md files

### 4.1 Where a rule goes
- A script can check it → hook or Gate A script. It doesn't need to be in a prompt.
- Always true in one folder → that folder's CLAUDE.md. Claude Code loads it whenever it reads a file there, so the model doesn't have to choose to load it. I expect this to be more reliable on a 27B model, but the pilot should confirm it.
- Long how-to for one kind of task → a skill.
- Before each slice, the orchestrator loads the checklist for that stack (short per-topic lists, not the full skill), so a rule that must be followed should also be a checklist line.
- `.claude/rules/*.md` with a `paths:` glob works like a folder CLAUDE.md, if your version has it **(unverified)**. Folder CLAUDE.md files are shared with your team; if you can't commit them yet, use `CLAUDE.local.md` (git-ignored) or `.claude/rules/`.

### 4.2 CLAUDE.md files (placeholder paths)
```
midnight-api/CLAUDE.md                scope, questions, checking, git, naming
  services/evermore/CLAUDE.md         CRUD + real-data validation; transactions
  services/evermore/tests/CLAUDE.md   the inventory test model
  services/twilight/CLAUDE.md         reverse proxy rules + what to test
  libs/midnight_models/CLAUDE.md      models only
  frontend/CLAUDE.md                  frontend rules a script can't check
```

**Root `midnight-api/CLAUDE.md`**
```markdown
# midnight-api
evermore = CRUD service, validates real data · twilight = reverse proxy · midnight_models = shared models only.

## Scope
New code follows the conventions. Existing lines change only when the task needs them changed.
Don't rename, reformat, retype, reorder or "fix" existing code for conventions, even in a file you're editing.

## Asking me questions
Before asking about a requirement, quote my words for the requirement verbatim, then ask.

## Checking
Say something works, passes, or is how the architecture behaves only after checking it, and show the output.
If you can't check it, say so and raise it as an open problem.

## Git
- One branch per ticket: BTRC-<n>-short-description. Never create a second branch for the same BTRC-<n>.
- At the end of a merge: pull the base branch (master, the branch I named, or the one we're based on today).
- End of branch: commit, pull --rebase on the base, push the feature branch with --force-with-lease, make sure
  the pipeline passes, stop this branch's containers, remove the worktree.

## Python
- New functions never start with get_: entity_by_id, not get_entity_by_id.
- Full years: 2026, not 26.
- Strings of 5+ words are constants. Except where reading them in place matters: error messages, raise, settings.
- New routers use prefix=, not tags=.
- No # noqa, # type: ignore, # pylint: disable. Fix the code instead.

## Frontend
- No eslint-disable, @ts-ignore, @ts-expect-error. Fix the code instead.
```

**`services/evermore/CLAUDE.md`**
```markdown
# evermore (CRUD)
- Validation of real data happens here, not in midnight_models.
- Every session operation runs in a transaction: with self._session.begin_nested():
- Keep the try: self._session.commit() + handle_integrity_error(...) block as written in each function,
  even when it repeats. Don't extract it.
```

**`services/evermore/tests/CLAUDE.md`**
```markdown
# evermore tests
General pytest style: the pytest-conventions skill. This file wins where they differ.

## One environment per package, one view per test
- Package environment: built once per test package (a top-level folder under tests/, e.g. tests/entities),
  thrown away when the package ends. All modules in the package share it.
- Per test: the same rows (not a copy), re-read into a session that rolls back when the test ends.
- Everything runs inside one outer transaction that is never committed.
- While a package runs, the database holds exactly what its initialize_*_environment built.

## Fixtures, and who may request them
| Fixture | Scope | Request it from a test? |
|---|---|---|
| package_env_session | package | Never. Only inside initialize_*_environment |
| module_env | package | Never. It's the live builder session |
| env | function | Yes: read the inventory (env.entities, env.projects, ...) |
| session | function | Yes: for writes, and to refresh rows you changed |

package_env_session is imported in each package's conftest, never registered in the root conftest
(pytest only honors package scope in that package's own conftest). Every package conftest looks like:

    import pytest

    from ..env_fixtures import package_env_session
    from .entities_test_utils import initialize_test_environment

    @pytest.fixture(scope="package")
    def module_env(package_env_session):
        return initialize_test_environment(package_env_session)

    @pytest.fixture
    def env(module_env, session):
        return module_env.migration_session(session)

A package may build several environments on package_env_session; they share the savepoint and are discarded together.

## The environment is an inventory
- Tests fetch what they need from env and declare exactly what they need. They never build rows.
- Missing a row? Add it in initialize_*_environment, with its migrate_session entry. Never work around it in the test.
- A test must pass whatever else is added to the environment later. Environments only grow.
- Every time-valued column gets creation_and_time_generator.get_and_inc(), never a literal or now(),
  so no two rows share a timestamp. Not only the column you sort by today.

## One unit per test
- A test exercises one unit: the updater, the reader, the creator, or the endpoint.
  The environment (data) and the assertion are as dumb as possible.
- Never create with the creator and check with the reader: two units can agree on a wrong answer,
  and the extra validation and queries are charged to the test.
- Whole-response assertions build the expected value with the test's own formatter (e.g. format_entity_full)
  from the env row. The formatter converts by itself. It may import production model classes,
  never production conversion logic.

## Control flow (tests too)
- Explicit checks: len(items) == 0, value is None. Booleans: `if is_ready:`, never `== True` / `is True`.
- Never `value or default`; write `if value is None: value = default`.
- No else after return/raise/break.
```
Optional extra rule (not in your notes): "don't assert on the count or order of all rows; filter to the rows the test fetched." It's the usual way a test breaks when the environment grows.

**`services/twilight/CLAUDE.md`**
```markdown
# twilight (reverse proxy)
- Twilight doesn't know the shapes it passes. Bodies and responses are dict[str, JsonValue] or
  list[dict[str, JsonValue]]. Never import the models of the services it calls.
- List endpoints always take SupportsPagination(), SupportsFilters() and SupportsSort().
- Pass-through endpoints: one-line docstring, no :param:/:return:.
## Tests
- Pass-through routes (most routes, straight to evermore) get no tests.
- Routes with logic (e.g. the MongoDB parts) get tests: mock the downstream HTTP service,
  assert the forwarded request and the returned body.
```

**`libs/midnight_models/CLAUDE.md`**
```markdown
# midnight_models
Shared models of midnight-api. Models only (pydantic is fine).
- No functions, no validators, no raising errors. Validation happens in evermore, on the real data.
- Export every new model from the package's __init__.py.
- No tests here; the models are tested through the services that use them.
```

**`frontend/CLAUDE.md`**
```markdown
# frontend
Full rules: the vue-conventions skill. The ones that matter most:
- SFC order: <template> (one wrapper element) → <script lang="ts"> (types only) → <script setup lang="ts"> → <style>.
- No export interface in .vue. Shared types → src/models/, shared functions → src/utils/. Prefer utils over composables.
- Props: withDefaults(defineProps<Props>(), {...}). Emits: interface Emits { 'name': [Type, Type] }, no param names.
- No consts in <script setup>.
- Spacing: ms/me/ps/pe only, never ml/mr/pl/pr (RTL).
- Colors: Vuetify theme classes for text (text-entryText), Vuetify tokens for surfaces and borders,
  never hex/rgb. Check light and dark.
- Tailwind only, no d-flex/d-block. w-full/h-full, not w-[100%]. flex for sizing, rem for fonts, else vh/vw/%.
- No any; unknown + narrowing when the shape is truly unknown. === / !== only.
  Explicit checks: val !== null && val !== undefined, str.trim().length === 0, arr.length === 0.
- Every async view: loading, empty (with a message) and error states. Errors via showGlobalSnackbar, no console.log.
- API calls only under requests/.
- No eslint-disable, @ts-ignore, @ts-expect-error. Fix the code instead.
```

### 4.3 Skills
| Skill | Change |
|---|---|
| `python-conventions` | Done: full years. To do: decisions 2–4; flat over nested (blocks over ~10 lines become named functions); move the twilight, midnight_models and SQL sections into their CLAUDE.md files / `sql-conventions`; split the checklist into short per-topic lists the orchestrator loads per slice. |
| `pytest-conventions` | Keep AAA, naming, parametrize, `pytest.raises(match=)`, explicit checks. Remove the `db_session` and factory examples (decision 5), and fix the `email or f"..."` example, which breaks the no-`or`-default rule. Add "a service's `tests/CLAUDE.md` wins". Same cleanup in `backend-test-infra`. |
| `sql-conventions` | New: the evermore transaction rules, with examples. |
| `vue-conventions` | Add what's missing (I searched the skill for these): `withDefaults`, kebab-case `.ts` files, no `console.log`, `w-full`/`h-full`, splitting big components, the emits format, no consts in `<script setup>`, ms/me/ps/pe, utils over composables, and Beatrice's list (empty/loading states, `Promise.all`, infinite scroll, `showGlobalSnackbar`, `requests/`, typed refs, `watch(..., { immediate: true })`), no eslint-disable / @ts-ignore / @ts-expect-error, and strings of 4+ words as constants (deliberately lower than Python's 5+). |
| `grill-with-docs` | The requirements list in your words, quote-first questions (§2.3). |
| `test-plan` | The four-column format (§2.8); drop layers, IDs, coverage map and results. |
| `finish-branch` | Not needed as a skill: it's the `finish_branch.py` script (§2.7). |
| `harvest-findings` | Later, once there are 3–5 Beatrice logs. |

### 4.4 Hooks and scripts
- `post_edit_checks.py`: report changed lines only.
- `guard_branch.py`: new.
- `next_step.py`: new Stop hook (§2.2).
- `check_slice.py` / `gate_a.py`: new. Lint, types, tests, coverage, scope (out-of-scope files, changed existing lines) and new suppressions; `gate_a.py` also keeps the dismissed-findings list.
- `finish_branch.py`: new (§2.7).
- `run_beatrice.py`: new (§2.5). `agents/explorer.md`: explores the whole scope, writes `explore/explorer-<n>.md`.
- `check_python_conventions.py`: full years; `get_` on new function names (PY-62, names in the base version and framework overrides are skipped); `or` used as a default (PY-56).
- All of them are installed with `install.sh` (§0, decision 11); the hooks are user-level, so every workflow hook exits at once when `MIDNIGHT_ROLE=reviewer`, and the edit and test-plan hooks act only while an approved feature runs.

---

## 5. Order of work
1. **Pilot.** Run today's `/feature` on one past ticket and time it: minutes per subagent, turns per task, whether the model keeps to the phases, and how many Beatrice findings you get at the end.
2. Build what helps either way: the changed-lines hook, `guard_branch.py`, and the CLAUDE.md files.
3. Update the skills (§4.3).
4. Write `next_step.py`, `check_slice.py`, `gate_a.py`, `run_beatrice.py`, `finish_branch.py`, and change `/feature` to use them.
5. Run the same ticket again and compare with step 1. Add extra reviewers or more rounds only where the numbers show a gap.
