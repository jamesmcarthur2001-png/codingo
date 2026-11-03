# evermore (CRUD)
- Validation of real data happens here, not in midnight_models.
- database/create/ and database/update/: the main modules there hold only managers (creators, updaters).
  Anything else, like helper functions, goes in utils.py (or another utils module), never next to a manager.
- Exception classes only in the errors file(s), and general: NotFoundError, AlreadyExistsError, ConflictError.
  The message names the object. Reuse an existing error before adding one.
- Tests use the test database only, never the database in .env (see tests/CLAUDE.md).
- One migration per branch: update the branch's migration instead of adding a second one.
- Never put session calls (add, commit, refresh, ...), try/except blocks or ORM models, fields and queries into
  reusable helpers, base models or mixins. Write them out each time; a little duplication keeps each function readable.
- A manager never constructs another manager: it gets them through dependency injection.
- Batch, never loop: no session call, query or *_by_id once per element of a loop. One
  select(...).where(col.in_(ids)), session.add_all(...), one bulk delete; raise when the count comes back short.
- A creator/updater returns the read model the endpoint answers with; the endpoint never calls convert_to_get_* itself.
- One prefix per message: the manager's message names the object and the reason; the endpoint's except adds
  "Failed to <action> <object>: ". Never both.
- Don't re-validate what a constraint already refuses: no _validate_*_exist for a link/FK whose insert raises anyway.
- A uniqueness rule lives in the database: when a SELECT enforces a name rule, the branch's migration also gets the
  (partial) unique index. The SELECT is the friendly message, the index is the rule. Reusing a sibling's rule:
  copy its comparison too (lower(trim(...))).
- Search filters mirror the sibling entity's filter model (SupportsSort, ...), even when the frontend doesn't use it
  yet, and every field of a filter model has a column behind it, or the generic reader answers 500.
- An endpoint catches every error the manager it calls raises: read the manager's :raises:, catch them all.
- Deleting a row drops the link rows that point at it, in both directions.
- get_: forbidden on manager methods that fetch (entity_by_id, entity_by_id_raw, entity_by_id_internal);
  required on dependency-injection providers and on general getters that aren't SQL related.
- Every session operation runs in a transaction: with self._session.begin_nested():
- Keep the try: self._session.commit() + handle_integrity_error(...) block as written in each function,
  even when it repeats. Don't extract it.
