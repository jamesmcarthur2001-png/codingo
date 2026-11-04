# Python Checklist: Docstrings, Naming & Comments

Applies to code you write or change. Never to unchanged lines. Answer each item ✅, ❌ (with `file:line`), or N/A. Exemptions for tests and migrations: see `checklist.md`.

## Docstrings
- [ ] PY-14 (auto) Opening and closing `"""` are on their own lines in every docstring
- [ ] PY-15 (auto) No blank lines between `:param` / `:return` / `:raises` lines
- [ ] PY-16 (auto) `__init__` methods have no docstring
- [ ] PY-29 (auto) No blank line between a class docstring and the class body
- [ ] PY-17 Docstrings of business-logic functions have `:param` / `:return` / `:raises` as needed; small helpers may have only the description
- [ ] PY-35 (auto for presence) Every function and method has a docstring (except `__init__` and tests). Judge by hand that endpoint docstrings have only a description, with no `:param`/`:return`/`:raises`.
- [ ] PY-18 Description is one compact sentence ending in `.` that says generally what the function or class does, not its exact behaviour step by step; it doesn't mention raising errors. `:param`/`:return`/`:raises` lines are short
- [ ] PY-41 (auto) Function, method, and endpoint descriptions are in the imperative mood (`Lock the resource.`, not `Locks the resource.`)
- [ ] PY-42 (auto) Boolean returns say what the value means (`:return: Whether the asset is overdue.`), never `True when ..., False when ...`
- [ ] PY-20 Proxy pass-through functions have a single-line docstring only
- [ ] PY-21 No docstring mentions past implementations

## Naming
- [ ] PY-22 Function and variable names say exactly what they handle (no `load`, `process`, `data`, `item`)
- [ ] PY-36 (auto) No single-letter or abbreviated names (`q`, `db`, `e`, `err`, `idx`, ...) for variables, parameters, loop variables, or `except ... as`. Short external names use `alias=`.
- [ ] PY-62 A function that fetches a model by its id is named with `by_id` when possible (`entity_by_id`, `entity_by_id_raw`, `entity_by_id_internal`); `get_` itself is fine
- [ ] PY-85 (auto) A function that returns `bool` is named as a question (`is_name_valid`, `has_children`, `can_archive`)
- [ ] PY-86 (auto) No function starts with `_reject` / `_accept` (or `reject_` / `accept_`): it's `_validate_<what>`

## Comments
- [ ] PY-52 (auto) No comments at all: the only `#` lines are section banners. A line that "needs" a comment gets a better variable or function name instead
