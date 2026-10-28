# Python Checklist: Typing, Layout & Tooling

Applies to code you write or change. Never to unchanged lines. Answer each item ✅, ❌ (with `file:line`), or N/A. Exemptions for tests and migrations: see `checklist.md`.

## Typing
- [ ] PY-01 (auto) Every function parameter has a type annotation (except `self`/`cls`)
- [ ] PY-02 (auto) No function is annotated `-> None`
- [ ] PY-03 (auto) No `return None`, except in functions annotated `-> X | None`
- [ ] PY-04 (auto) No trailing bare `return` as the last statement of a function
- [ ] PY-05 Every function that returns a value has a return annotation
- [ ] PY-06 Local annotations only where the type isn't obvious (empty collections, unions, untyped external values). No `count: int = 0` style annotations.

## File layout
- [ ] PY-07 (auto) File starts with the page docstring, containing a description, `:author:` and `:date: DD/MM/YYYY` (full year: 2026, never 26)
- [ ] PY-08 (auto) Section banners match `# ----- Name ----- #` and the name is capitalized
- [ ] PY-09 (auto) `Imports` banner is on the line right after the closing `"""`, with 1 blank line below
- [ ] PY-10 (auto) `Consts` banner has 1 blank line above and 1 below
- [ ] PY-11 (auto) `Classes` / `Functions` / domain banners have 1 blank line above and 2 below
- [ ] PY-12 No empty banner sections
- [ ] PY-13 (auto) No `__all__` in application packages

## Tooling
- [ ] PY-28 Dependencies added with `uv add`, and commands run through `uv run`
- [ ] PY-50 `mypy --strict` passes on the changed lines (`check_slice.py` / `gate_a.py` in the workflow, `scripts/mypy_strict.py` outside it), never silenced with `-> None`
