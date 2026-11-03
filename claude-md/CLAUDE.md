# midnight-api

Monorepo:
- `evermore`: the CRUD service. Validation of real data happens here.
- `twilight`: the reverse proxy in front of the services.
- `midnight_models`: shared models only.
- `web/sunrise`: the frontend, Vue 3 + Vuetify + TypeScript + Tailwind.

Each of these folders has its own CLAUDE.md with its rules; it loads when you work there.
Detailed conventions are in the skill for the language or test layer you're working in:
python-conventions, sql-conventions, pytest-conventions, backend-test-infra, vue-conventions,
vitest-conventions, browser-test-conventions.

## Checking your work
- Frontend: `npx nx affected -t lint --base=origin/<base>`, then the same with `-t typecheck` and `-t test`.
- Python, from the service folder: `uv run pytest <test file>`, `uv run ruff check <path>`, `uv run mypy --strict <package>`.
- TODO (fill in): how to start the local stack, and a one-test-file example for each service.
- Tests run only on a test database (the test setup's own, or the branch's `docker compose -p btrc-<n>` stack),
  never on the user's own database (the one in `.env`, the default compose project, the usual dev port).
  Check which database URL the tests will use before running them. Not sure? Ask; don't run them.
- Say that something works or passes only together with the command output that shows it.
  If you can't check something, say so in your final message under "Open problems". Don't guess.

## Tests
- No tests in twilight. Don't write, plan or run tests for it; its changed lines need no coverage.
- Each test checks one thing, and calls one production unit. Never create with one function and check with another
  (creator then reader): it's slower and the second can hide the first one's bug. Check through the models instead.
- A test package's environment (tests/<module>/) is built and changed only in its initialize_test_environment,
  and only with the service's own model classes, never with production functions.

## Scope
Change existing lines only when the task needs them changed, even in a file you're editing:
no renaming, reformatting, retyping or reordering of code that already breaks the conventions.
This holds for tests too: a test the task doesn't need stays byte-identical, including another module's tests and
the ones that came from the base branch.
New code follows the conventions skills, not the nearby code.

## Questions
Before asking about a requirement, quote the user's words for it verbatim, then ask.

## Code review
Map every problem first: list each finding (file:line, what's wrong, fix or dismiss with a reason) before changing anything.
A verifier's `sure` is always fixed, `invalid` never is; `unsure` is your call. Then fix them all, and run the checks once at the end.

## Git
- The base branch is master, unless the user names another one.
- One branch per ticket: `BTRC-<n>-short-description`. Reuse it; never create a second branch for the same ticket.
- Commits, merge requests and pushes: a title only, no description (no body, no trailers).
- Commit title: `<type>(<service>): <what was done>`, e.g. `feat(sunrise): add CSV export`.
  The type is what the change is (`feat`, `fix`, `refactor`, `test`, `docs`, `chore`); the scope is the service it changes;
  several services are joined by a comma and a space: `feat(evermore, frontend): add CSV export`.
- MR title: the same plus ` (BTRC-<n>)`. Several tickets: join the parts with ` & `, each with its own ticket:
  `feat(sunrise): add CSV export (BTRC-1234) & fix(frontend): keep the date filter (BTRC-1240)`.
- A branch is finished only when all four hold: rebased on the latest base (`git pull --rebase origin <base>`, pushed with
  `--force-with-lease`), the pipeline of the pushed commit passed (`glab ci status --branch <branch>`; a failed job:
  `glab ci trace <job> --branch <branch>`, fix, push again), every container of the branch closed
  (`docker compose -p btrc-<n> down`), and its worktree closed. Never call it done before that.
- Before every commit to a feature branch (a pipeline fix, a quick fix, inside or outside /feature), run
  `python3 "$HOME/.claude/scripts/check_changes.py" --base <base>` and fix what it lists.
- Never push to the base branch. After a merge, pull the base branch.
- `/feature` runs only when the user types it. Inside it, follow the command's own steps: its scripts do
  the git steps, and after the spec is approved it asks no questions.

## Python, every service
- Manager methods that fetch something never start with `get_`: `entity_by_id`, `entity_by_id_raw` or
  `entity_by_id_internal`, not `get_entity_by_id`. Dependency-injection providers and general getters that aren't SQL
  related must start with `get_`.
- Full years in dates: 2026, not 26.
- Keep docstrings short: one sentence on what the function or class is for, not how it works.
  Don't narrate its steps, branches or edge cases; the code already says that. `:param:`/`:return:` lines are a few words each.
- Readability over reuse, always: session calls (add, commit, refresh, ...), try/except blocks and ORM objects
  (models, fields, queries) never become shared helpers, base models, mixins or factories. A little duplicated code
  is fine: each function and each model stays readable on its own.
- Never generate a model's fields with a function; write each field in the model.
- One migration per branch: when the schema changes again, update the branch's migration, never add a second.
- String constants in the backend: only keys (see below). Never an error message or anything raised.
- No `# noqa`, `# type: ignore`, `# pylint: disable`, `# pyright: ignore` or `# pragma: no cover`. Fix the code.
  The one exception: a single `# pylint: disable=duplicate-code` on its own line, directly above a function or class that deliberately mirrors its sibling. Never inside a body, docstring, call or signature, never another pylint check, and never a `# pylint: enable`.

## Comments
Never write code comments, in any language. Needing one means the code can be simpler: give the value a clear
variable name, or move the step into a function whose name says what it does.

## Frontend
- No `eslint-disable`, `@ts-ignore` or `@ts-expect-error`. Fix the code.
- A string becomes a constant only when it's a long sentence (6+ words) used in more than one place, or a key.
  Everything else stays inline, error messages included.

## Keys are constants, everywhere
Keys that must match in several places (storage and cache keys, header names, queue and routing keys, event names,
permission names, the keys of a dictionary one service sends another) are constants, in the backend and in the
frontend. Each service keeps its own constant for each key it shares, so it's easy to change. Error messages and
what you raise are never constants.
