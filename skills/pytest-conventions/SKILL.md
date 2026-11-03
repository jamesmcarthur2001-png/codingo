---
name: pytest-conventions
description: Use when writing, maintaining, reviewing, or debugging Python tests with pytest. Enforces AAA structure, fixture scoping, parametrization, DAMP test naming, pytest.raises with match, explicit checks, 100% coverage, and strict isolation. A service's tests/CLAUDE.md wins where it differs.
---

# Pytest Testing Conventions

Applies to code you write or change. Never to unchanged lines.

Opinionated, comprehensive testing patterns for Python and pytest. Incorporates proven patterns from `pytest-patterns`, `pytest-best-practices`, and `python-testing-patterns`. Follow these instructions whenever writing, refactoring, or reviewing Python tests.

**A service's `tests/CLAUDE.md` wins where it differs** (e.g. `services/evermore/tests/CLAUDE.md` defines evermore's inventory test model: package environments, `env`/`session` fixtures, never build rows in a test). Use that service's own fixtures; this skill covers the general style.

---

## 1. Core Principles

1. **Test behavior, not implementation**: Focus on what the code does and its observable contract, not internal private implementation details.
2. **Arrange-Act-Assert (AAA), Visibly**: Visibly separate every test function into three distinct blocks using single blank lines: setup (Arrange), the single action under test (Act), and verification (Assert).
3. **Each test checks one thing**: one behavior, one outcome. Multiple `assert` statements are permitted only when they check the same single result. Two things to check → two tests (or a parametrized one).
4. **One unit per test**: a test calls one production unit and checks it with plain data, never with another production unit. Don't create with the creator and then check with the reader (or update then read, or call one endpoint to check another): it's slower, and the second unit can hide a bug in the first, since both can agree on a wrong answer. Read what the unit wrote straight from the database through the models, or compare with the returned object.
5. **Test environments are built in one place**: the data a test package uses (`tests/<module>/`) is created and changed only in its `initialize_test_environment` (or `initialize_*_environment`). Tests, fixtures and helpers read it and never add, change or delete its rows.
6. **The environment uses only the service's own models**: `initialize_test_environment` builds rows with the main service's model classes directly (`Entity(...)`, `session.add(...)`), never with production managers, creators, helpers or another package's code. Building through production code would hide the very bugs the tests should find.
7. **DAMP over DRY in tests**: Descriptive And Meaningful Phrases over rigid Don't Repeat Yourself. Tests should be readable from top to bottom without jumping through complex helper abstractions.
8. **Fixtures over setup methods**: Never use `unittest`-style `setUp`/`tearDown` or classes. Use pytest fixtures in `conftest.py` or module files.
9. **Narrow fixture scopes**: Default to `function` scope. Widen to `module` or `session` only for expensive, read-only setup (e.g. database engines, mock servers).
10. **Parametrize instead of looping**: Never write a `for` loop inside a test function. Loops hide which iteration failed; `@pytest.mark.parametrize` yields isolated, uniquely identified test cases.
11. **Isolation and order-independence**: Zero shared mutable state across tests. Tests must pass regardless of execution order and run cleanly in parallel (e.g. with `pytest-xdist`).
12. **Mock at the boundary you own**: Patch where the object is *imported and looked up*, not where it is defined. Mock external network, filesystem, and clocks; never mock the unit under test.
13. **No comments**: not even `# Arrange` / `# Act` / `# Assert`; the blank lines show them.

### What a test owns
- **The package's environment holds the rows that package is about**, in every state its tests assert about. If `tests/cases/` tests cases and their variants, its `initialize_test_environment` creates them. A test never manufactures its own subject, unless it tests the creation of that thing.
- **A test never writes outside the unit under test**: no `session.commit()`, no direct mutation of a row to stage a state. A state a test needs is a row in the environment.
- **Assert about the rows your test created or touched**, never that a whole table is empty or has N rows. Search by the ids you made and expect `None`. With shared, growth-only fixture data, a whole-table assertion is wrong now and broken by the next addition.
- **Nothing you don't own is counted or indexed**: no literal row counts, no positional selection (`rows[0]`), no hard-coded ids. Select by an explicit predicate with its exclusions spelled out, and compare against the fixture's own collection.
- **Every assertion names the mistake it catches.** Picture one plausible wrong implementation; if the test still passes, it isn't an assertion. An assertion that was already true before the act counts as none.
- **A test the task doesn't need stays byte-identical**, including tests of another module and tests that came from the base branch.

### Validators, filters, sorting and query counts
- **A validator shared by create and update is tested through both**, not once.
- **A filter is tested against an independent Python re-implementation of its rule** over the fixture data, compared as sets, never against a hand-written list of expected ids (that pins the fixture's contents and breaks when it grows). A new filter field updates that re-implementation in the same commit.
- **Every field of a filter model gets a test that exercises it**, so a field with no column behind it fails a test instead of answering 500 to a user.
- **Sort and pagination get fixture rows that differ only in the sorted column.**
- **Query counts**: where the suite has a query or invocation-count mechanism, a new method that loops over a collection pins its count in the same commit, and an existing count constant is lowered when a change reduces the count. Where the number comes from goes in the constant's name (e.g. `EXPORT_QUERIES_ONE_PER_TABLE = 3`), not in a comment.

### Before any run
- Read which database the run resolves to and confirm it is a test database. Never create or drop anything in one you're unsure of.
14. **100% test coverage**: All new business logic, models, services, and endpoints require 100% test coverage.
    - *Exception*: twilight (the reverse proxy) has no tests at all.

---

## 2. Test File & Directory Organization

### Directory Structure & Layout

Mirror the source tree layout inside the `tests/` directory:

We have `tests/`, a shared `tests/utils/` package, and a directory for each module (e.g. `entities`, `entity_types`):

```
tests/
  conftest.py                        root fixtures
  utils/                             shared test helpers, one file per subject
    general.py
    project.py
  <module_name>/                     one directory per module (e.g. entities, entity_types)
    conftest.py                      only the module_env and env fixtures
    <module_name>_test_utils.py      the module's helpers and its initialize_test_environment
    test_<what_we_test>.py
```

- **Helpers**: shared helpers go in `tests/utils/<subject>.py` (`general.py`, `project.py`, …); a module's own helpers and its `initialize_test_environment` go in `tests/<module>/<module>_test_utils.py`. There is no `utils.py` in a module directory.
- **`conftest.py` in a module holds only `module_env` and `env`.** Any other fixture lives at the top of the test file that uses it.
- **Path format**: `tests/<module_name>/test_<what_we_test>.py`.
- **Test function naming**: `test_<unit>_<condition>_<expected>`:
  - `test_create_user_duplicate_email_raises_duplicate_user_error`
  - `test_calculate_discount_zero_percent_returns_original_price`
  - `test_verify_token_expired_signature_returns_false`

### Internal Test File Structure

Every test file must follow this strict sequence:
1. **Imports straight away**: Standard library, third-party, application code under test.
2. **Local Fixtures**: Module-specific fixtures immediately following imports.
3. **Test Functions**: Standalone functions (`def test_*`).
   - **No classes in test files** unless strictly necessary.
   - **No code comments in test files**, ever. Tests must be self-explanatory.

---

## 3. The AAA Structure in Action

Every test body must visually separate Arrange, Act, and Assert:

```python
def test_calculate_discount_valid_percentage_reduces_total():
    # Arrange
    base_price: float = 100.0
    discount_percentage: float = 20.0

    # Act
    discounted_price: float = calculate_discount(base_price, discount_percentage)

    # Assert
    assert discounted_price == 80.0
```
*(Omit the `# Arrange`, `# Act`, `# Assert` comment labels in production test files; preserve the blank line separation).*

---

## 4. Fixture Patterns & Scoping

### Conftest Hierarchy

Fixtures cascade downwards from root `tests/conftest.py` into module-level `conftest.py` files. Database sessions and test data come from the service's own fixtures, as its `tests/CLAUDE.md` describes; never add a parallel database fixture.

### Yield Fixtures (Automatic Cleanup)

Always use `yield` fixtures when setup requires cleanup or teardown:

```python
@pytest.fixture
def temp_cache_dir(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    yield cache_dir
    # Cleanup occurs automatically via tmp_path
```

---

## 5. Parametrization & Data-Driven Tests

Never use loops inside test methods. Use `@pytest.mark.parametrize`:

```python
@pytest.mark.parametrize("input_email,is_valid", [
    ("user@domain.com", True),
    ("first.last@company.org", True),
    ("missing-at.com", False),
    ("@no-username.org", False),
    ("", False),
])
def test_email_validator_various_inputs(input_email: str, is_valid: bool):
    validation_result: bool = validate_email_address(input_email)

    assert validation_result is is_valid
```

---

## 6. Testing Exceptions & Error Paths

Always test error branches and custom exception handling. Use `pytest.raises` with exact exception types and message matching:

```python
def test_withdraw_insufficient_funds_raises_overdraft_error():
    account: BankAccount = BankAccount(balance=50.0)

    with pytest.raises(InsufficientFundsError, match="Requested 100.0 but balance is 50.0"):
        account.withdraw(100.0)
```

Never assert generic `Exception` or `ValueError` when domain exceptions are defined.

---

## 7. Explicit Checks (tests too)

- Empty: `if len(items) == 0:` / `assert len(items) == 0`, never `if not items:`.
- None: `if value is None:`, never `if not value:`.
- Booleans: `if is_ready:` / `assert is_ready`, never `== True` / `is True`.
- **Never `value or default`**: it silently swallows every falsy value (`0`, `""`, `[]`). Write the check out:

```python
# GOOD:
def build_user_payload(user_id: str, email: str | None = None) -> dict[str, str]:
    if email is None:
        email = f"test-{user_id}@example.com"

    return {"id": user_id, "email": email}

# BAD:
def build_user_payload(user_id: str, email: str | None = None) -> dict[str, str]:
    return {"id": user_id, "email": email or f"test-{user_id}@example.com"}
```

- No `else` after `return` / `raise` / `break`.

---

## 8. Mocking Best Practices

- **Patch where the name is used/imported**:
  If `services/user.py` imports `send_email` from `utils/email.py`, patch `services.user.send_email`, NOT `utils.email.send_email`.
- **Deterministic Time**: Use `monkeypatch` or `freezegun` to freeze clock values in time-dependent tests.
- **Never mock the subject under test**: Only mock external network calls, system timers, and third-party APIs.

---

## 9. Test Layers & Infrastructure

Backend features are tested on two layers:

- **Integration tests**: call the service manager/reader directly (e.g. the entities reader) against a real test database. They cover business logic, ORM behavior, and edge cases without HTTP.
- **API tests**: call the endpoint through the FastAPI test client. They cover routing, validation, status codes, and response shapes.

Every new endpoint gets both layers. Database, Mongo, Temporal, and RabbitMQ test setups are described in the **`backend-test-infra`** skill. Reviewers use `references/checklist.md`.

---

## 10. Running Tests

Always execute test commands with `uv`:

```bash
uv run pytest
uv run pytest tests/auth/test_login_flow.py
uv run pytest -k "test_login" -v
uv run pytest -m "not slow"
```
