# Python Checklist: Conditions, Flow & Calls

Applies to code you write or change. Never to unchanged lines. Answer each item ✅, ❌ (with `file:line`), or N/A. Exemptions for tests and migrations: see `checklist.md`.

## Conditions
- [ ] PY-23 (auto for annotated names) No truthy/falsy checks on non-bool values. Uses `is None` / `is not None` / `len(x) == 0`.
- [ ] PY-56 (auto) No `or` used as a default (`name or "Unknown"`, `entity or value`): `if name is None: name = "Unknown"`, or a full conditional
- [ ] PY-45 `if` conditions that do real work (a query, chained calls, several combined checks) are moved into a well-named variable first
- [ ] PY-47 (auto for if/elif chains on one value) Behavior that depends on a type or key is a dict lookup (type → value, handler, or class), not a chain of `if`/`elif` per type
- [ ] PY-32 (auto) Exactly one blank line after every `if` block (with its `elif`/`else`) that is followed by more code in the same block, including the last block of a chain

## Flow
- [ ] PY-57 Early returns: a loop body that is one `if` inverts it and `continue`s; a function body that is one `if` inverts it and `return`s
- [ ] PY-63 No `else` after a branch that ends in `return` / `raise` / `break` / `continue`
- [ ] PY-64 When both branches return and the `if` branch is long while the `else` branch is short, the condition is inverted (short case first, then the long case unnested)
- [ ] PY-65 Flat over nested: a block over ~10 lines is a function with a name
- [ ] PY-66 No `pass` placeholder blocks (`if ...: pass`, `except ...: pass`); an otherwise empty class ending in `pass` (PY-39) is fine
- [ ] PY-58 `try` / `except` blocks and a write's `try: self._session.commit()` + `handle_integrity_error(...)` block are written out where they're used, not extracted into helpers

## Comprehensions, calls & literals
- [ ] PY-38 (auto) Comprehensions and generator expressions: expression, each `for`, and each `if` on their own lines; brackets on their own lines
- [ ] PY-24 (auto) Calls with 3+ arguments, or whose single-line form would make the line 70+ characters (indentation included), have one argument per line and a trailing comma
- [ ] PY-44 (auto) List and set literals with two or more items have one item per line, brackets on their own lines, and a trailing comma (a literal of at most 30 characters may stay on one line)
