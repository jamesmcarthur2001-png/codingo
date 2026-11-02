# SQL Conventions Checklist

Applies to code you write or change. Never to unchanged lines.

Run this per changed `.py` file that uses a database session or declares a table model. Every item must be answered ✅, ❌ (with `file:line`), or N/A.

- [ ] SQL-01 Every session operation (read, add, update, delete) runs inside `with self._session.begin_nested():`
- [ ] SQL-02 Every write keeps its `try: self._session.commit()` + `handle_integrity_error(...)` block written out in the function, even when it repeats. It is never extracted into a helper.
- [ ] SQL-06 No helper bundles session steps (`add` + `commit` + `refresh`, or any mix of `add`, `flush`, `commit`, `refresh`, `delete`); each step is written where it happens
- [ ] SQL-03 No `self._session.rollback()` (was PY-40): the `begin_nested()` block rolls back its savepoint
- [ ] SQL-07 The branch has at most one migration; later schema changes update it instead of adding another
- [ ] SQL-08 No shared base model, mixin or field-building function for ORM models, and no helper that returns a reusable query
- [ ] SQL-04 Indexes and constraints are declared in `__table_args__` at the end of the model, never on the field (`index=True`)
