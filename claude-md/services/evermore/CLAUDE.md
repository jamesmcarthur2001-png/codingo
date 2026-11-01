# evermore (CRUD)
- Validation of real data happens here, not in midnight_models.
- database/create/ and database/update/: try to keep only manager classes there. Helpers go in utils.py
  (or another utils module), not as loose functions next to a manager.
- Exception classes only in the errors file(s), and general: NotFoundError, AlreadyExistsError, ConflictError.
  The message names the object. Reuse an existing error before adding one.
- List endpoints: a realistic page size (what one page shows, usually 10–25), never 100.
- Tests use the test database only, never the database in .env (see tests/CLAUDE.md).
- Every session operation runs in a transaction: with self._session.begin_nested():
- Keep the try: self._session.commit() + handle_integrity_error(...) block as written in each function,
  even when it repeats. Don't extract it.
