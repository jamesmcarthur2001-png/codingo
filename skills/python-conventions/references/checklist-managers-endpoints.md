# Python Checklist: Managers, Endpoints & the Database

Applies to code you write or change. Never to unchanged lines. Answer each item ✅, ❌ (with `file:line`), or N/A. Details: `python-conventions` §17.

- [ ] PY-74 (auto) No manager constructs another manager; managers come in through dependency injection
- [ ] PY-75 (auto for session calls and `*_by_id` in a `for`) No session call, query or `*_by_id` per element of a loop: one `select(...).where(col.in_(ids))`, `session.add_all(...)`, bulk delete; a short count raises
- [ ] PY-76 A creator or updater returns the read model the endpoint answers with; no endpoint calls `convert_to_get_*`
- [ ] PY-77 (auto for managers) One prefix per message: the manager names object and reason, the endpoint's `except` adds `Failed to <action> <object>: `; no manager message starts with `Failed to`
- [ ] PY-78 No `_validate_*_exist` for a link or foreign key whose insert raises anyway
- [ ] PY-79 A name rule enforced by a `SELECT` also has its (partial) unique index in the branch's migration, with the same comparison as the sibling it copies (e.g. `lower(trim(...))`)
- [ ] PY-80 A search filter mirrors the sibling entity's filter model (`SupportsSort`, …), and every filter field has a column behind it
- [ ] PY-81 Every endpoint catches every error listed in the `:raises:` of the manager methods it calls
- [ ] PY-82 Deleting a row also deletes the link rows pointing at it, in both directions
- [ ] PY-83 (auto) No `dict[str, Any]` in a pydantic or SQLModel model; use a model or `dict[str, JsonValue]`
- [ ] PY-84 Dependency-injection providers and non-SQL getters start with `get_`
