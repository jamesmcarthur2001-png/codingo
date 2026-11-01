# midnight-api

Monorepo:
- `evermore`: the CRUD service. Validation of real data happens here.
- `twilight`: the reverse proxy in front of the services.
- `midnight_models`: shared models only.
- `frontend`: Vue 3 + Vuetify + TypeScript + Tailwind.

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

## Scope
Change existing lines only when the task needs them changed, even in a file you're editing:
no renaming, reformatting, retyping or reordering of code that already breaks the conventions.
New code follows the conventions skills, not the nearby code.

## Questions
Before asking about a requirement, quote the user's words for it verbatim, then ask.

## Code review (beatrice-code-review)
Map every problem first: list each comment (file:line, what's wrong, fix or dismiss with a reason) before changing anything.
Then fix them all, and run the checks once at the end.

## Git
- The base branch is master, unless the user names another one.
- One branch per ticket: `BTRC-<n>-short-description`. Reuse it; never create a second branch for the same ticket.
- Commits, merge requests and pushes: a title only, no description (no body, no trailers).
- Commit title: `<type>(<service>): <what was done>`, e.g. `feat(sunrise): add CSV export`.
  The type is what the change is (`feat`, `fix`, `refactor`, `test`, `docs`, `chore`); the scope is the service it changes;
  several services are joined by a comma and a space: `feat(evermore, frontend): add CSV export`.
- MR title: the same plus ` (BTRC-<n>)`. Several tickets: join the parts with ` & `, each with its own ticket:
  `feat(sunrise): add CSV export (BTRC-1234) & fix(frontend): keep the date filter (BTRC-1240)`.
- Finishing a branch: `git pull --rebase origin <base>`, push with `--force-with-lease`, then wait until the pipeline passes
  (`glab ci status --branch <branch>`; a failed job: `glab ci trace <job> --branch <branch>`, fix, push again).
  Only then stop the branch's containers (`docker compose -p btrc-<n> down`) and close its worktree.
- Never push to the base branch. After a merge, pull the base branch.
- `/feature` runs only when the user types it. Inside it, follow the command's own steps: its scripts do
  the git steps, and after the spec is approved it asks no questions.

## Python, every service
- New functions never start with `get_` (`entity_by_id`, not `get_entity_by_id`). Existing names stay.
- Full years in dates: 2026, not 26.
- Keep docstrings short: one sentence on what the function or class is for, not how it works.
  Don't narrate its steps, branches or edge cases; the code already says that. `:param:`/`:return:` lines are a few words each.
- Readability over sharing: no helper that bundles session steps (add + commit + refresh in one call), and no
  function that returns a shared class part (e.g. a pydantic Field used by many models). Write them out where used.
- String constants: none by length in the backend; only critical keys (see below) are constants.
- Page sizes are what one page really shows (usually 10–25), never 100 "just in case".
- No `# noqa`, `# type: ignore`, `# pylint: disable`, `# pyright: ignore` or `# pragma: no cover`. Fix the code.

## Frontend
- No `eslint-disable`, `@ts-ignore` or `@ts-expect-error`. Fix the code.
- Strings of more than 6 words become constants; shorter strings stay inline.

## Critical keys, everywhere
Keys that must match in several places (storage and cache keys, header names, queue and routing keys, event names,
permission names) are constants, in the backend and in the frontend.
