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
3. **One assertion concept per test**: A test verifies a single outcome or behavior. Multiple `assert` statements are permitted only when validating properties of the same single result.
4. **DAMP over DRY in tests**: Descriptive And Meaningful Phrases over rigid Don't Repeat Yourself. Tests should be readable from top to bottom without jumping through complex helper abstractions.
5. **Fixtures over setup methods**: Never use `unittest`-style `setUp`/`tearDown` or classes. Use pytest fixtures in `conftest.py` or module files.
6. **Narrow fixture scopes**: Default to `function` scope. Widen to `module` or `session` only for expensive, read-only setup (e.g. database engines, mock servers).
7. **Parametrize instead of looping**: Never write a `for` loop inside a test function. Loops hide which iteration failed; `@pytest.mark.parametrize` yields isolated, uniquely identified test cases.
8. **Isolation and order-independence**: Zero shared mutable state across tests. Tests must pass regardless of execution order and run cleanly in parallel (e.g. with `pytest-xdist`).
9. **Mock at the boundary you own**: Patch where the object is *imported and looked up*, not where it is defined. Mock external network, filesystem, and clocks; never mock the unit under test.
10. **100% test coverage**: All new business logic, models, services, and endpoints require 100% test coverage.
    - *Exception*: Pure reverse proxy redirect endpoints without business logic do not require test suites.

---

## 2. Test File & Directory Organization

### Directory Structure & Layout

Mirror the source tree layout inside the `tests/` directory:

We have `tests/`, and then directories for each module (e.g. `entities`, `entity_types`, etc.).
Inside each module directory, we have the module's `conftest.py` and `utils` files:

```
tests/
  conftest.py                   # Root/global session fixtures
  <module_name>/                # Directory for each module (e.g., entities, entity_types)
    conftest.py                 # Module-specific fixtures
    utils.py                    # Module test helpers and mock utilities (or utils/ directory)
    test_<what_we_test>.py      # Test files for this module
```

- **Module Utils**: Use the `utils` files located inside each module directory for module-specific test helpers and mocks.
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
   - **No code comments in test files** unless strictly necessary to document a non-obvious upstream workaround. Tests must be self-explanatory.

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
