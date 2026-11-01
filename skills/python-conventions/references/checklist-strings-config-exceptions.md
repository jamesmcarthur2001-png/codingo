# Python Checklist: Strings, Config, Models, FastAPI & Exceptions

Applies to code you write or change. Never to unchanged lines. Answer each item ✅, ❌ (with `file:line`), or N/A. Exemptions for tests and migrations: see `checklist.md`.

## Strings & configuration
- [ ] PY-34 Critical keys (storage/cache keys, header names, queue and routing keys, event names, permission names) are named constants, defined once
- [ ] PY-55 No other string is a constant: messages, SQL, templates and settings stay inline whatever their length (the more-than-6-words rule is frontend only). Strings in tests stay inline.
- [ ] PY-68 List endpoints and queries use a realistic page size (what one page shows, usually 10–25), never a default of 100 or more
- [ ] PY-33 (auto for URL and localhost literals) URLs, hosts, ports, DB names, credentials, and keys come from `.env` via settings (never hardcoded)

## Classes & models
- [ ] PY-30 (auto) Table models: `__tablename__` is on the line right after the class docstring
- [ ] PY-31 (auto) Table models: `__table_args__` (constraints, indexes) is at the end of the class, after the fields
- [ ] PY-43 (auto) String enums inherit from `StrEnum`, never `str, Enum`
- [ ] PY-46 (auto) Pydantic field validation uses `Annotated[..., BeforeValidator(...)]` / `AfterValidator(...)`, not `@field_validator` methods

- [ ] PY-71 No function returns a shared class part (a pydantic/SQLModel `Field(...)`, a validator, a `model_config`) for several classes to reuse; each class writes its fields out

## Readable duplication
- [ ] PY-72 No helper bundles `try`/`except` blocks or session steps (`add` + `commit` + `refresh` and similar) for its callers; see `sql-conventions` SQL-02 and SQL-06

## FastAPI
- [ ] PY-37 (auto) Dependencies are functions passed with `Depends(...)` in each endpoint's signature, never stored in a constant or type alias
- [ ] PY-67 New routers use `prefix=`, not `tags=`

## Exceptions
- [ ] PY-25 (auto) No raising of builtin exceptions (`Exception`, `ValueError`, `KeyError`, `RuntimeError`, …)
- [ ] PY-26 (auto) Custom exception class names end with `Error`
- [ ] PY-39 (auto) A class whose body is only a docstring ends with `pass`
- [ ] PY-27 Each custom exception is a general kind of failure (`NotFoundError`, not `EntityNotFoundError`); an existing general error is reused
- [ ] PY-69 (auto) Exception classes are defined only in errors files (`errors.py`, `errors/`, `*_errors.py`)

## Suppressions & private members
- [ ] PY-53 (auto) No suppressions at all (`# noqa`, `# type: ignore`, `# pylint: disable`, `# pyright: ignore`, `eslint-disable`). `check_slice.py` and `gate_a.py` fail on any new one.
- [ ] PY-54 (auto) No private member (`_name`) of another class or module is used or imported
