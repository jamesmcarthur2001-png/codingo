# evermore tests
General pytest style: the pytest-conventions skill. This file wins where they differ.

## One environment per package, one view per test
- Package environment: built once per test package (a top-level folder under tests/, e.g. tests/entities),
  thrown away when the package ends. All modules in the package share it.
- Per test: the same rows (not a copy), re-read into a session that rolls back when the test ends.
- Everything runs inside one outer transaction that is never committed.
- While a package runs, the database holds exactly what its initialize_*_environment built.

## Fixtures, and who may request them
| Fixture | Scope | Request it from a test? |
|---|---|---|
| package_env_session | package | Never. Only inside initialize_*_environment |
| module_env | package | Never. It's the live builder session |
| env | function | Yes: read the inventory (env.entities, env.projects, ...) |
| session | function | Yes: for writes, and to refresh rows you changed |

package_env_session is imported in each package's conftest, never registered in the root conftest
(pytest only honors package scope in that package's own conftest). Every package conftest looks like:

    import pytest

    from ..env_fixtures import package_env_session
    from .entities_test_utils import initialize_test_environment

    @pytest.fixture(scope="package")
    def module_env(package_env_session):
        return initialize_test_environment(package_env_session)

    @pytest.fixture
    def env(module_env, session):
        return module_env.migration_session(session)

A package may build several environments on package_env_session; they share the savepoint and are discarded together.

## The environment is an inventory
- Tests fetch what they need from env and declare exactly what they need. They never build rows.
- Missing a row? Add it in initialize_*_environment, with its migrate_session entry. Never work around it in the test.
- A test must pass whatever else is added to the environment later. Environments only grow.
- Every time-valued column gets creation_and_time_generator.get_and_inc(), never a literal or now(),
  so no two rows share a timestamp. Not only the column you sort by today.

## One unit per test
- A test exercises one unit: the updater, the reader, the creator, or the endpoint.
  The environment (data) and the assertion are as dumb as possible.
- Never create with the creator and check with the reader: two units can agree on a wrong answer,
  and the extra validation and queries are charged to the test.
- Whole-response assertions build the expected value with the test's own formatter (e.g. format_entity_full)
  from the env row. The formatter converts by itself. It may import production model classes,
  never production conversion logic.

## Control flow (tests too)
- Explicit checks: len(items) == 0, value is None. Booleans: `if is_ready:`, never `== True` / `is True`.
- Never `value or default`; write `if value is None: value = default`.
- No else after return/raise/break.
