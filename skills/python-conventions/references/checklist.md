# Python Conventions Checklist (index)

Applies to code you write or change. Never to unchanged lines.

The checklist is split into short per-topic lists. Before each slice, load the lists for the topics the slice touches; a full review goes through all four.

| List | Covers |
|---|---|
| `checklist-typing-layout.md` | Typing, file layout and banners, tooling (PY-01 to PY-13, PY-28, PY-50) |
| `checklist-docstrings-naming.md` | Docstrings, naming, `get_` prefix, comments (PY-14 to PY-22, PY-29, PY-35, PY-36, PY-41, PY-42, PY-52, PY-62) |
| `checklist-conditions-calls.md` | Conditions, `or` defaults, flat code, comprehensions, multiline calls and literals (PY-23, PY-24, PY-32, PY-38, PY-44, PY-45, PY-47, PY-56 to PY-58, PY-63 to PY-66) |
| `checklist-strings-config-exceptions.md` | String constants, `.env`, classes and models, FastAPI, exceptions, suppressions and private members (PY-25 to PY-27, PY-30, PY-31, PY-33, PY-34, PY-37, PY-39, PY-43, PY-46, PY-53 to PY-55, PY-67) |

Database sessions, transactions and indexes: the `sql-conventions` checklist (PY-40 moved there as SQL-03).
twilight rules: `services/twilight/CLAUDE.md`. midnight_models rules: `libs/midnight_models/CLAUDE.md`. (PY-48, PY-49, PY-59, PY-60 and PY-61 moved there.)

## How to run
- In the `/feature` workflow, `scripts/check_slice.py` and `scripts/gate_a.py` run the convention checker, ruff, eslint and `mypy --strict` (through `scripts/mypy_strict.py`) on the changed lines only. Copy their result for the items marked (auto), then judge the rest.
- Outside the workflow, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/check_python_conventions.py" <files>` and judge only the lines you changed.
- Never add `-> None` to silence mypy.

## Scope
- Run per changed `.py` file (tests use the pytest checklist as well).
- Migration files (Alembic `versions/` / `migrations/`) are exempt from every item.
- Test files are exempt from PY-01, PY-07 to PY-12, PY-17 to PY-21, PY-24, PY-33, PY-34, PY-35, PY-41, PY-42, and PY-55.
- Every item must be answered ✅, ❌ (with `file:line`), or N/A.
