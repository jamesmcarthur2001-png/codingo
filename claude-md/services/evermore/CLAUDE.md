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
- Every session operation runs in a transaction: with self._session.begin_nested():
- Keep the try: self._session.commit() + handle_integrity_error(...) block as written in each function,
  even when it repeats. Don't extract it.
