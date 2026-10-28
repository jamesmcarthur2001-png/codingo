# Python Checklist: Strings, Config, Models, FastAPI & Exceptions

Applies to code you write or change. Never to unchanged lines. Answer each item ✅, ❌ (with `file:line`), or N/A. Exemptions for tests and migrations: see `checklist.md`.

## Strings & configuration
- [ ] PY-34 Strings of 5+ words (SQL, templates, long non-error messages) are named constants. Error messages, anything in `raise`, strings inside models and error classes, settings and similar stay inline, even when repeated. Strings in tests stay inline.
- [ ] PY-55 No constant holds a short string (4 words or fewer) or a settings string (settings stay inline). The 5+ threshold is deliberately higher than the frontend's 4+.
- [ ] PY-33 (auto for URL and localhost literals) URLs, hosts, ports, DB names, credentials, and keys come from `.env` via settings (never hardcoded)

## Classes & models
- [ ] PY-30 (auto) Table models: `__tablename__` is on the line right after the class docstring
- [ ] PY-31 (auto) Table models: `__table_args__` (constraints, indexes) is at the end of the class, after the fields
- [ ] PY-43 (auto) String enums inherit from `StrEnum`, never `str, Enum`
- [ ] PY-46 (auto) Pydantic field validation uses `Annotated[..., BeforeValidator(...)]` / `AfterValidator(...)`, not `@field_validator` methods

## FastAPI
- [ ] PY-37 (auto) Dependencies are functions passed with `Depends(...)` in each endpoint's signature, never stored in a constant or type alias
- [ ] PY-67 New routers use `prefix=`, not `tags=`

## Exceptions
- [ ] PY-25 (auto) No raising of builtin exceptions (`Exception`, `ValueError`, `KeyError`, `RuntimeError`, …)
- [ ] PY-26 (auto) Custom exception class names end with `Error`
- [ ] PY-39 (auto) A class whose body is only a docstring ends with `pass`
- [ ] PY-27 Each custom exception represents a clear domain failure

## Suppressions & private members
- [ ] PY-53 (auto) No suppressions at all (`# noqa`, `# type: ignore`, `# pylint: disable`, `# pyright: ignore`, `eslint-disable`). `check_slice.py` and `gate_a.py` fail on any new one.
- [ ] PY-54 (auto) No private member (`_name`) of another class or module is used or imported
