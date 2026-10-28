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
- Say that something works or passes only together with the command output that shows it.
  If you can't check something, say so in your final message under "Open problems". Don't guess.

## Scope
Change existing lines only when the task needs them changed, even in a file you're editing:
no renaming, reformatting, retyping or reordering of code that already breaks the conventions.
New code follows the conventions skills, not the nearby code.

## Questions
Before asking about a requirement, quote the user's words for it verbatim, then ask.

## Git
- The base branch is master, unless the user names another one.
- One branch per ticket: `BTRC-<n>-short-description`. Reuse it; never create a second branch for the same ticket.
- Rebase on the base before pushing, push with `--force-with-lease`, and never push to the base branch.
- After a merge, pull the base branch.
- `/feature` runs only when the user types it. Inside it, follow the command's own steps: its scripts do
  the git steps, and after the spec is approved it asks no questions.

## Python, every service
- New functions never start with `get_` (`entity_by_id`, not `get_entity_by_id`). Existing names stay.
- Full years in dates: 2026, not 26.
- No `# noqa`, `# type: ignore`, `# pylint: disable`, `# pyright: ignore` or `# pragma: no cover`. Fix the code.

## Frontend
- No `eslint-disable`, `@ts-ignore` or `@ts-expect-error`. Fix the code.
