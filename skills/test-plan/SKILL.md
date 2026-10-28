---
name: test-plan
description: Use in the feature workflow after implementation and before writing any test. Produces test-plan.md, exactly one table with four columns (test name, what it checks, expected result, file), one row per test, covering every requirement, edge case, and new code path. Tests may only be written once they are listed here. Coverage exemptions and test results go to state.md.
---

# Test Plan

Write `docs/features/<slug>/test-plan.md` from `templates/test-plan.md`. **No test code is written before this file exists.**
- A hook blocks writing any test whose name isn't in `test-plan.md`.
- Gate A treats every file in the File column as allowed scope, so list every test file you'll create or change.

## Format
`test-plan.md` is exactly one table, and nothing else (no layers, IDs, coverage map, or results):

| Test name | What it checks | Expected result | File |
|---|---|---|---|
| `test_entity_by_id_missing_id_raises_entity_not_found_error` | Reading an entity id that doesn't exist | Raises `EntityNotFoundError` with "Entity 7 was not found." | `tests/entities/test_read_entity.py` |

## Inputs
- `spec.md`, `plan.md`, `state.md`.
- The diff of the implementation: `git diff <base>...HEAD` plus uncommitted changes.
- The reference test files from `patterns.md`, and the service's `tests/CLAUDE.md`.

## Rules
1. **One row per test function.** A parametrized test is one row; list the cases in "What it checks".
2. **Test name holds the exact name:**
   - pytest: the function name, `test_<unit>_<condition>_<expected>`.
   - Vitest: the exact `it(...)` string, e.g. `shows an error message when loading entities fails`.
   - Playwright: the exact `test(...)` string, e.g. `user creates an entity and sees it in the list`.
3. **File holds the exact path** the test will live in, following `pytest-conventions` / `vitest-conventions` / `browser-test-conventions` and the service's `tests/CLAUDE.md`.
4. **Expected result is observable:** a return value, status code plus body, raised exception plus message, DB state, emitted event, rendered text, URL. "Works correctly" isn't a result.
5. **What to plan:**
   - Every requirement and edge case in `spec.md` has at least one row.
   - Every new public function, endpoint, component, consumer, workflow, and activity has at least one row, and every error branch in the diff has one.
   - Backend: each new endpoint is tested through its service manager/reader **and** through the API (`backend-test-infra`).
   - Frontend: components (props, emits, loading/error/empty states) and views/flows in Vitest; one browser test per new user journey plus its main failure (`browser-test-conventions`). Behavior moved from jsdom to a browser test says so in "What it checks".
   - Pure proxy pass-through routes get no rows.
6. Don't plan tests that only restate the implementation (e.g. "the mock was called") when a real result can be checked.

## Self-check
- [ ] The file is one four-column table and nothing else
- [ ] Every requirement and edge case in `spec.md` has a row
- [ ] Every new endpoint has both a service-level and an API row
- [ ] Every row's expected result is concrete
- [ ] Names follow the naming conventions exactly, and every test file is in the File column

## After writing the tests
Run the tests and the changed-line coverage. Write the results to `state.md`, not to `test-plan.md`. Changed lines that stay uncovered for a good reason (e.g. a pure proxy pass-through route) go under `## Coverage exemptions` in `state.md`, one line each:
```markdown
## Coverage exemptions
- services/twilight/routes/entities.py:40-52: pass-through route, no business logic
```
If a planned test turns out to be impossible or wrong, change its row instead of silently dropping it.
