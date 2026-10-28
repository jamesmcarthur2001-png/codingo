---
name: python-conventions
description: Use when creating, modifying, refactoring, or testing Python backend code. Enforces typing standards, docstrings on every function and endpoint (imperative mood), naming (no new get_ functions), page/section headers, class and SQLModel layout, StrEnum, Annotated pydantic validators, readable and flat if conditions, mappings over if chains, blank lines after if blocks, multiline calls, collection literals and comprehensions, FastAPI dependencies and router prefixes, custom exceptions, .env configuration, string constants (5+ words), no comments, no suppressions or private access, uv usage, and references the pytest-conventions and sql-conventions skills.
---

# Python Backend Conventions

Applies to code you write or change. Never to unchanged lines.

Strict conventions for Python backend development. Follow these rules whenever writing, refactoring, or testing Python code.

Checklists: `references/checklist.md` is an index of short per-topic lists. Before each slice, load the lists for the topics the slice touches; reviewers go through all of them.

Folder rules (twilight, midnight_models, evermore) live in their CLAUDE.md files, and sessions, transactions and indexes in the **`sql-conventions`** skill (§14).

---

## 1. Package Management

Use **`uv`** for every package and environment operation:

- Add dependencies with `uv add <package>` (dev-only: `uv add --dev <package>`). Never use `pip install` directly.
- Sync the environment with `uv sync`.
- Run every tool through uv: `uv run pytest`, `uv run mypy`, `uv run python <script>`.

---

## 2. Typing Guidelines

- **Function & Method Signatures**:
    - All function and method parameters **must** have explicit type annotations.
    - Return types **must** be explicitly annotated for all non-None returns (e.g. `-> str`, `-> list[Item]`, `-> tuple[int, bool]`).
- **The `None` Return Rule**:
    - If a function returns nothing or returns None, **do NOT write `-> None`**. Omit the return type annotation completely.
    - **Never write `return None`** (except in `-> X | None` functions, see Optional Returns below). Use a bare `return` only for an early exit.
    - Do **not** add a trailing `return` at the end of a function. Reaching the end of a function already returns None.
- **Local Variable Typing**:
    - Do **NOT** add redundant type annotations on obvious assignments (e.g., `count: int = 0`, `name: str = "alice"`, `is_active: bool = True` is bad and unnecessary).
    - Use type annotations on local variables **only when it is not clear what type the variable is** (e.g., empty collections like `items: list[UserRecord] = []`, complex union returns, or when initializing from untyped external returns).
    - If you are not sure whether the type is clear, **always add the type annotation**.
- **Static Verification**:
    - In the `/feature` workflow, `scripts/check_slice.py` and `scripts/gate_a.py` run the convention checker, ruff, eslint and `mypy --strict` (through `scripts/mypy_strict.py`, which drops only the errors the no-`-> None` rule causes) on the changed lines only.
    - Outside the workflow, run `python "${CLAUDE_PLUGIN_ROOT}/scripts/check_python_conventions.py" <files>` and judge only the lines you changed. For types use `python "${CLAUDE_PLUGIN_ROOT}/scripts/mypy_strict.py" <package>`, never plain mypy.
    - Never add `-> None` to silence mypy.
- **Optional Returns**: In a function annotated `-> X | None`, write `return None` explicitly. mypy rejects a bare `return` there ("Return value expected").

```python
# GOOD:
def save_user_profile(user_id: str, email: str):
    """
    Save the profile of a user.
    """
    user_record: dict[str, str] = {"id": user_id, "email": email}
    active_tokens: list[str] = []
    user_store.insert(user_record)


def deactivate_user(user: UserRecord):
    """
    Mark an active user as inactive.
    """
    if not user.is_active:
        return

    user.is_active = False


# BAD:
def save_user_profile(user_id, email) -> None:  # Do NOT use -> None and do NOT leave parameters untyped
    count: int = 0  # Redundant typing on obvious literal assignment
    user_record = {"id": user_id, "email": email}
    user_store.insert(user_record)
    return None  # Do NOT write return None (and no trailing return is needed at all)
```

---

## 3. Page Header and Section Structure

Every Python application file must follow a consistent top-level layout with page documentation and stylized section dividers. Exempt:
- Empty files (e.g. an empty `__init__.py`).
- **Test files** (`tests/`, `test_*.py`, `conftest.py`). They have no page docstring and no section banners (see `pytest-conventions`).
- **Migration files** (Alembic `versions/` / `migrations/`). They're generated and keep the generator's format, so they need no page header, banners, or docstring format, and their generated `-> None` signatures stay as they are.

The page docstring holds a description, `:author:`, and `:date: DD/MM/YYYY` (full year: 2026, never 26). Section lines are exactly `# ----- Name ----- #`, with the name **always capitalized**. Standard section names: `Imports`, `Consts`, `Classes`, `Functions` (and other domain-specific sections as needed, e.g. `Routes`). Omit sections that would be empty.

### Strict Spacing Rules

1. `# ----- Imports ----- #`:
    - Placed **straight after the closing (2nd) `"""`** of the page docstring, on the very next line, with **0 blank lines** in between.
    - Exactly **1 blank line** below the section line before imports start.
2. `# ----- Consts ----- #`:
    - Exactly **1 blank line** above the section line.
    - Exactly **1 blank line** below the section line.
3. `# ----- Classes ----- #`, `# ----- Functions ----- #` (and domain sections such as `Routes`):
    - Exactly **1 blank line** above the section line.
    - Exactly **2 blank lines** below the section line.

### Full Example

```python
"""
Service manager for reading entities.

:author: <your name>
:date: 16/10/2026
"""
# ----- Imports ----- #

from sqlmodel import Session, select

from app.entities.models import Entity

# ----- Consts ----- #

DEFAULT_PAGE_SIZE = 50

# ----- Classes ----- #


class EntityNotFoundError(Exception):
    """
    Raised when the requested entity does not exist.
    """
    pass

# ----- Functions ----- #


def read_entity_by_id(session: Session, entity_id: int) -> Entity:
    """
    Read one entity by its id.

    :param session: The open database session.
    :param entity_id: The id of the entity to read.
    :return: The entity.
    :raises EntityNotFoundError: When no entity has this id.
    """
    entity: Entity | None = session.get(Entity, entity_id)
    if entity is None:
        raise EntityNotFoundError(f"Entity {entity_id} was not found.")

    return entity
```

### `__init__.py` Files

- Do **NOT** define `__all__` in application packages (only acceptable in a reusable public library where restricting the interface is mandatory).
- Omit empty banner sections.

---

## 4. Docstrings and Documentation Rules

### Function Docstrings Format

Every function and method has a docstring, in this exact format:

```python
"""
DOCSTRING EXPLANATION

:param PARAM_NAME: WHAT IT DOES
:return: WHAT WE RETURN
:raises ERROR_NAME: WHEN WE RAISE
"""
```

- **Always On Separate Lines**: Opening `"""` and closing `"""` must **always** be on their own separate lines (never placed on the same line as the description or content). This applies universally across all docstrings (functions, classes, modules, and exceptions).
- **No empty lines between fields**: `:param:`, `:return:`, and `:raises:` must appear on consecutive lines with zero blank lines between them.
- **Every function has a docstring**: every function and method in application code has one, including small helpers, managers, and endpoints. Exceptions: `__init__`, and test functions and fixtures (their names explain them).
- **Which fields**: functions with business logic get `:param:`, `:return:` (when they return a value), and `:raises:` (when they raise). Small helpers without business logic may have only the description.
- **Never mention past implementations**: Explain *why* the code works this way *now*, never what it used to do.
- **No code comments**: never write `#` comments. Names, types, and docstrings explain the code. The only `#` lines are the section banners (§3).
- **Description Sentence**: The description is a short, concise sentence explaining what the function does, ending with a period (`.`). It must **never** mention raising errors (e.g. no "or raise an error if not found"). Exceptions are documented exclusively in `:raises:`.
- **Imperative mood**: function, method, and endpoint descriptions are written as a command: `Lock the resource.`, `List sites matching the search text.`, never `Locks the resource.` or `Lists sites ...`. Class and exception docstrings describe the thing, so they keep their form (`A site where assets are installed.`, `Raised when ...`).
- **Boolean returns**: describe what the value means, not when it's true or false. Write `:return: Whether the asset is overdue.`, never `:return: True when the asset is overdue, False otherwise.` The same applies to the description of a function that returns a `bool`: `Check whether the name is taken.`
- **API Endpoint Functions**: always have a docstring with **only** a short description of what the endpoint does (e.g. `List sites matching the search text, one page at a time.`). Do **NOT** include `:param:`, `:return:`, or `:raises:`.
- **Reverse Proxy / Pass-Through Endpoints**: If an endpoint or function is just a reverse proxy redirecting/forwarding requests without internal business logic, omit `:param:`, `:raises:`, and `:return:`. Write only a brief single-line explanation. Full `:param:`, `:return:`, `:raises:` docstrings apply only when business logic is present.
- **Classes & `__init__`**: Classes get a standard description with opening `"""` on line 1, description on line 2, and closing `"""` on line 3 (no `:param:` or `:return:`). `__init__` methods do **NOT** get a docstring.
- **No blank line after a class docstring**: the class body (`__init__`, attributes, `__tablename__`, anything) starts on the line right after the closing `"""`.
- **Indicative Naming**: Never use vague or generic names like `load` or `process`. Use explicit names that explain what is being handled (e.g., `load_customer_billing_history`, `process_credit_card_charge`).
- **No `get_` prefix on new functions**: name what is returned: `entity_by_id`, not `get_entity_by_id`. Existing names (`get_session`, `get_and_inc`) stay as they are; call them, don't rename them.
- **No short or abbreviated names**: no single-letter names and no abbreviations (`q`, `db`, `e`, `ex`, `err`, `idx`, `tmp`, `cfg`, `val`, `obj`, `res`, `req`, `resp`, `msg`, ...) for variables, parameters, loop and comprehension variables, or `except ... as` names. Write the full word: `query`, `session`, `error`, `index`. When an external name must stay short (e.g. a `?q=` query parameter), keep the full Python name and map it: `query: Annotated[str | None, Query(alias="q")] = None`.

---

## 5. Conditions and `if` Blocks

### Explicit condition checks
Never use truthy/falsy checks (`if not x:` / `if x:`) unless `x` is a genuine `bool`.

- Checking for None: `if x is None:` / `if x is not None:`
- Checking for an empty collection or string: `if len(x) == 0:` / `if len(x) > 0:`
- **Never pick a value with `or`** (`entity or value`, `name or "Unknown"`, `items or []`). It silently swallows every falsy value (`0`, `""`, `[]`). Write the full check, so it's clear what you check: `if name is None: name = "Unknown"`, or `entity if entity is not None else value`.

### Early returns
When the rest of a block depends on a condition, check the opposite condition and leave early. A loop whose body is one `if` inverts it and `continue`s; a function whose body is one `if` inverts it and `return`s.

```python
# GOOD:
for asset in assets:
    if asset.status != AssetStatus.ACTIVE:
        continue

    schedule_inspection(asset)

# BAD:
for asset in assets:
    if asset.status == AssetStatus.ACTIVE:
        schedule_inspection(asset)
```

### No `else` after `return` / `raise` / `break`
When the `if` branch ends with `return`, `raise`, `break` or `continue`, the `else` is dead weight: drop it and dedent its body.

When both branches return and the `if` branch is long while the `else` branch is short, invert the condition: handle the short case first and return, then write the long case without nesting.

```python
# GOOD:
if site is None:
    return DEFAULT_TIMEZONE

timezone = resolve_site_timezone(site)
...
return timezone

# BAD:
if site is not None:
    timezone = resolve_site_timezone(site)
    ...  # many lines
    return timezone
else:
    return DEFAULT_TIMEZONE
```

### Flat over nested
- A block (an `if` body, a loop body, a `with` body) of more than about **10 lines** becomes a function whose name says what it does.
- No `pass` placeholder blocks (`if ...: pass`, `except SomeError: pass`, `else: pass`): change the condition instead. The `pass` that ends an otherwise empty class (§12) is the one exception.

### Blank line after an `if` block
When more code follows an `if` block (including its `elif`/`else` branches) in the same function, class, or module, leave **exactly one blank line** after the block. In a chain of `if` blocks, that includes one blank line after the last one.

```python
# GOOD:
if project is None:
    raise ProjectNotFoundError(f"Project {project_id} was not found.")

if len(features) == 0:
    return

if is_active:
    activate_session(session)

publish_project(project)

# BAD:
if not project:  # project is not a bool
    raise ProjectNotFoundError(f"Project {project_id} was not found.")
if not features:  # use len(features) == 0; also missing the blank line above
    return
publish_project(project)  # missing the blank line after the if block
```

### Readable conditions
Keep the `if` line easy to read. When a condition does real work (runs a query, chains calls, combines several checks), move that work into a variable first and let its name say what is being checked. The `if` then reads like a sentence.

```python
# GOOD:
active_asset = session.exec(active_assets.limit(1)).first()
has_active_assets = active_asset is not None
if has_active_assets:
    raise SiteHasActiveAssetsError(f"Site {site_id} still has active assets.")

is_due_soon = next_due_date is not None and next_due_date <= today + REMINDER_WINDOW
if is_due_soon:
    notify_technicians(asset)

# BAD:
if session.exec(active_assets.limit(1)).first() is not None:  # what does this check?
    raise SiteHasActiveAssetsError(f"Site {site_id} still has active assets.")
```

A simple check (`if site is None:`, `if len(names) == 0:`, `if is_active:`) stays as it is.

### Mappings over long if chains
Make behavior that depends on a type or a key dynamic and generic: put it in a dict (type → value, handler, or class) and look it up, instead of one `if`/`elif` per type. Adding a type then means adding one entry, not another branch.

```python
# GOOD:
INSPECTION_HANDLERS: dict[AssetCategory, Callable[[Asset], Inspection]] = {
    AssetCategory.ELECTRICAL: build_electrical_inspection,
    AssetCategory.MECHANICAL: build_mechanical_inspection,
    AssetCategory.HVAC: build_hvac_inspection,
}

inspection = INSPECTION_HANDLERS[asset.category](asset)

# BAD:
if asset.category == AssetCategory.ELECTRICAL:
    inspection = build_electrical_inspection(asset)
elif asset.category == AssetCategory.MECHANICAL:
    inspection = build_mechanical_inspection(asset)
elif asset.category == AssetCategory.HVAC:
    inspection = build_hvac_inspection(asset)
```

---

## 6. Multiline Calls and Collection Literals

- A call (function call, constructor, decorator, `raise SomeError(...)`) **must** put each argument on its own line, with a trailing comma, when:
    - It has **3 or more arguments**, **or**
    - Written on a single line, **the whole line would be 70+ characters**, counting everything on it: indentation, spaces, the code before the call (e.g. `entity = `), and anything after it.
- Otherwise keep it on a single line.
- The trailing comma matters: it is what keeps formatters (`ruff format` / black) from collapsing the call back onto one line.

```python
# GOOD:
session.add(record)
raise HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail=str(error),
)

# BAD (as a single line it is 77 characters):
raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
```

### Collection literals
A list or set written with its items (two or more) puts each item on its own line, with the brackets on their own lines and a trailing comma after the last item. This applies inside calls too (e.g. a set passed to `frozenset(...)`), and in tests. Comprehensions follow §10.

The only exception is a really small literal, at most 30 characters from bracket to bracket (e.g. `["A", "B"]`, `{1, 2}`), which may stay on one line. Not sure whether it's small enough? Put each item on its own line.

```python
# GOOD:
STATUSES_WITHOUT_DUE_DATE = frozenset(
    {
        AssetStatus.OUT_OF_SERVICE,
        AssetStatus.RETIRED,
    },
)
SORTABLE_COLUMNS = [
    AssetSort.NAME,
    AssetSort.NEXT_DUE_DATE,
]

# BAD:
STATUSES_WITHOUT_DUE_DATE = frozenset(
    {AssetStatus.OUT_OF_SERVICE, AssetStatus.RETIRED},
)
SORTABLE_COLUMNS = [AssetSort.NAME, AssetSort.NEXT_DUE_DATE]
```

---

## 7. Class Layout and SQLModel Models

- The class body starts right after the class docstring, with no blank line (see §4).
- **SQLModel / SQLAlchemy table models** follow this order:
    1. the docstring
    2. `__tablename__`, on the line right after the docstring
    3. the fields
    4. `__table_args__` (constraints, indexes) and any other table configuration, **at the end of the class**
- Indexes are declared in `__table_args__`, never on the field (see `sql-conventions`).

```python
# GOOD:
class AssetType(SQLModel, table=True):
    """
    A kind of asset, with the number of days between its inspections.
    """
    __tablename__ = "asset_types"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, unique=True)
    inspection_interval_days: int

    __table_args__ = (
        CheckConstraint(
            "inspection_interval_days BETWEEN 1 AND 3650",
            name="ck_asset_types_inspection_interval_days_range",
        ),
    )
```

### String enums
An enum whose values are strings inherits from `StrEnum` (`from enum import StrEnum`), never `str, Enum`. Its members are real strings, so they compare, format, and serialize as their values.

```python
# GOOD:
class AssetStatus(StrEnum):
    """
    The working condition of an asset.
    """
    OPERATIONAL = "Operational"
    RETIRED = "Retired"


# BAD:
class AssetStatus(str, Enum):
    ...
```

### Pydantic validators
Prefer `Annotated` types with `BeforeValidator` / `AfterValidator` over `@field_validator` methods. The validation then sits on the field's type, and the same type can be reused on other models.

```python
# GOOD:
def validate_timezone(timezone: str) -> str:
    """
    Accept only IANA timezone names.

    :param timezone: IANA name such as Europe/Berlin.
    :return: The same name, when it resolves.
    :raises InvalidTimezoneError: When the name isn't a known IANA timezone.
    """
    ...


Timezone = Annotated[str, AfterValidator(validate_timezone)]


class SiteInput(BaseModel):
    """
    The values a client sends to create or update a site.
    """
    timezone: Timezone


# BAD:
class SiteInput(BaseModel):
    timezone: str

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, timezone: str) -> str:
        ...
```

---

## 8. Configuration (`.env`)

- **URLs, hosts, ports, database names, credentials, API keys, and every other environment-specific value** are stored in the service's `.env` file and read through the service's settings module. Never hardcode them in code, tests, or compose files when they can come from `.env`.

---

## 9. String Constants

- **Strings of 5+ words** (SQL, templates, multi-line text, long non-error messages) become named constants in the `Consts` section, so they're easy to find and change.
- **Except where reading the string in place matters**, whatever its length and even when it repeats: error messages, anything passed to `raise`, strings inside models and error classes, settings, and similar. Write them inline (`raise SiteNotFoundError(f"Site {site_id} was not found.")`).
- **Short strings** (4 words or fewer: keys, labels, `"Site not found"`) stay inline where they're used. Moving them into constants only hides them and makes quick changes slower.
- **Important keys are constants**: a specific string that matters, such as a settings key inside a dict, is a constant whatever its length, so it's easy to change in one place.
- **Strings in tests are never constants.**

---

## 10. Comprehensions

List, set, and dict comprehensions and generator expressions are written across lines, one part per line: the opening bracket stays on the line of the assignment (or call), then the expression, then each `for` clause, then each `if` clause, each on its own line, and the closing bracket on its own line.

```python
# GOOD:
site_names = [
    site.name
    for site in sites
    if not site.archived
]
has_blank_line = any(
    line.strip() == ""
    for line in lines
)

# BAD:
site_names = [site.name for site in sites if not site.archived]
```

---

## 11. FastAPI Endpoints and Dependencies

- **Every endpoint has a docstring** with only a short description (see §4).
- **Dependencies are functions**, such as the existing `get_session` and `get_current_user`, and every endpoint that needs one calls it in its own signature with `Depends(...)`. Those existing names keep their `get_`; a new dependency doesn't start with `get_` (e.g. `current_site`).
- **New routers use `prefix=`, not `tags=`**: `router = APIRouter(prefix="/sites")`.
- **Never store a dependency in a constant or a type alias** (no `SessionDependency = Annotated[Session, Depends(get_session)]` and no `session_dependency = Depends(get_session)`). Spelling the dependency in each endpoint keeps every endpoint readable on its own.
- Query and path parameters use full names (§4); use `alias=` when the URL needs a short name.

```python
# GOOD:
@router.get("/sites")
def list_sites(
    session: Annotated[Session, Depends(get_session)],
    query: Annotated[str | None, Query(alias="q", max_length=100)] = None,
) -> SitePage:
    """
    List sites matching the search text, one page at a time.
    """
    ...

# BAD:
SessionDep = Annotated[Session, Depends(get_session)]  # dependency stored in a constant


@router.get("/sites")
def list_sites(session: SessionDep, q: str | None = None) -> SitePage:  # no docstring, short name
    ...
```

Database access (sessions, transactions, queries) follows the **`sql-conventions`** skill.

---

## 12. Custom Exceptions

- **Never raise Python base exceptions** (`Exception`, `ValueError`, `KeyError`, `RuntimeError`, etc.).
- Always define and raise custom application exceptions that clearly represent the domain failure.
- Custom exception class names **must** end with `Error` (e.g. `NotFoundError`, `DatabaseTransactionError`, never `NotFound`).
- **Empty classes end with `pass`**: a class whose body would otherwise be only its docstring (typically an exception that just inherits) always has `pass` on the line after the docstring. Never leave a class with only a docstring.

```python
# GOOD:
class UserNotFoundError(Exception):
    """
    Raised when the specified user ID does not exist in the database.
    """
    pass


def fetch_user_by_id(user_id: str) -> UserRecord:
    """
    Fetch a user by id.

    :param user_id: The id of the user.
    :return: The user record.
    :raises UserNotFoundError: When no user has this id.
    """
    record: UserRecord | None = user_store.find(user_id)
    if record is None:
        raise UserNotFoundError(f"User {user_id} was not found.")

    return record
```

---

## 13. Testing Conventions (`pytest`)

Testing is governed by the dedicated **`pytest-conventions`** skill. Whenever writing, refactoring, or reviewing tests for Python backend code:

- **100% Test Coverage**: All new backend code requires 100% test coverage (pure reverse proxy redirects excepted).
- **Separate test database**: tests always run against their own database, never the application's, unless the user explicitly says otherwise (see `backend-test-infra`).

---

## 14. Folder Rules

- twilight rules: `services/twilight/CLAUDE.md`
- midnight_models rules: `libs/midnight_models/CLAUDE.md`
- evermore rules: `services/evermore/CLAUDE.md`
- Sessions, transactions, indexes: `sql-conventions`

---

## 15. Lint Suppressions and Private Members

- **No suppressions at all.** No `# noqa`, `# type: ignore`, `# pylint: disable=...`, `# pyright: ignore`, `eslint-disable`, or similar. Fix the code the tool reports. `check_slice.py` and `gate_a.py` fail on any new one.
- **Never use another class's or module's private members** (names starting with `_`): no `manager._build_query()`, no `from app.sites import _parse_row`. Use the public function. If none exists, make the needed function public in the module that owns it.
- Inside a class, `self._name` and `cls._name` are fine.

---

## 16. Readable Duplication

Some code is clearer written out where it's used than shared, even when it repeats. Don't extract helpers for:
- `try` / `except` blocks
- the `try: self._session.commit()` + `handle_integrity_error(...)` block of a write (see `sql-conventions`)

