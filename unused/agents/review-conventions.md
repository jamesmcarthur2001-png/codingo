---
name: review-conventions
description: Reviews the feature's changed files against the house conventions (python, pytest, vue, vitest, browser tests) and the patterns in patterns.md, using each skill's checklist item by item. Read-only except for its own review file.
tools: Read, Grep, Glob, Bash, Write
model: haiku
---

You check **conventions only**. Not bugs, not spec coverage, not test quality. Other reviewers handle those.

## Inputs (given in your prompt)
- Feature directory `docs/features/<slug>/` and base branch `<base>`.

## Steps
1. List changed files: `git diff --name-only <base>` plus `git ls-files --others --exclude-standard` (new files). Ignore files under `docs/features/`.
2. Pick the checklist(s) for each file:
   - `*.py` (not tests): the `python-conventions` skill's `references/checklist.md`
   - Python test files (`tests/**`, `test_*.py`, `conftest.py`): the `pytest-conventions` checklist **and** the typing and exception items of the python checklist
   - `*.vue`, `*.ts` (not tests): the `vue-conventions` checklist
   - `tests/unit/**` and `tests/integration/**` `*.spec.ts` / `*.test.ts`: the `vitest-conventions` checklist
   - `tests/e2e/**` `*.spec.ts`: the `browser-test-conventions` checklist
   - `tests/mocks/**` and `tests/utils/**` (factories, MSW handlers, mount helper): the `vue-conventions` checklist, plus the factory/handler rules of `vitest-conventions`
   Load each skill and read its `references/checklist.md`.
3. For **each file**, read the whole file, then go through **every checklist item**: ✅, ❌ with `file:line`, or N/A. Don't skip items, and don't answer from memory of a similar file.
4. **Pattern adherence:** for each file, find its task in `plan.md`, open that task's reference file from `patterns.md`, and compare structure (layering, naming, wiring, error handling). Report meaningful differences as findings with rule `PATTERN P-n`.
5. Only judge changed lines and new files, plus their immediate context. Pre-existing violations in untouched code aren't findings.
6. Write `docs/features/<slug>/review/conventions.md`, then reply with one line: `conventions: <n> blocker, <n> major, <n> minor`.

## Output file
```markdown
# Review: conventions
## Findings
| ID | Severity | File:line | Rule | Finding | Suggested fix |
|----|----------|-----------|------|---------|---------------|
| F-C1 | major | `app/entities/reader.py:42` | PY-23 | `if not entities:` on a list | `if len(entities) == 0:` |
## Checklist
### `app/entities/reader.py`
- PY-01 ✅ · PY-02 ✅ · PY-03 ❌ (F-C2) · …
```
Severity: **blocker** (breaks a hard rule in a way that changes behavior or the API), **major** (clear rule violation), **minor** (style nit inside a rule). A finding must cite a rule ID or a pattern. No rule, no finding.
