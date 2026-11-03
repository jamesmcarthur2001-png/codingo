# evermore tests
General pytest style: the pytest-conventions skill. This file wins where they differ.

## Test database only
Tests run on the test database, never on the user's own (the one in .env, or the default compose stack).
Before running them, check which database URL the test setup will connect to. If it's the user's: stop, and run them
with the test database's URL (or the branch's own `docker compose -p btrc-<n>` stack). Never create or drop anything
in a database you're not sure is a test one.

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
- A package's environment (tests/<module>/) is created and changed **only** in its initialize_test_environment
  (initialize_*_environment). Tests, fixtures and helpers read it; they never add, change or delete its rows.
- initialize_test_environment builds rows with evermore's own model classes only (Entity(...), session.add(...)).
  Never call production managers, creators or helpers there: a bug in them would then be built into the data,
  and the tests would agree with it instead of finding it.
- The environment holds the rows the package is about, in every state its tests assert about (tests/cases/ tests
  cases and variants, so its initialize_test_environment creates them). A test never manufactures its own subject,
  unless it tests the creation of that thing.
- Tests fetch what they need from env and declare exactly what they need. They never build rows.
- A test never writes outside the unit under test: no session.commit(), no direct mutation to stage a state.
- Assert about the rows your test created or touched, never that a table is empty or has N rows (search by the ids
  you made and expect None). Nothing you don't own is counted or indexed: no literal counts, no rows[0], no
  hard-coded ids; select by an explicit predicate and compare against the fixture's own collection.
- Missing a row? Add it in initialize_*_environment, with its migrate_session entry. Never work around it in the test.
- A test must pass whatever else is added to the environment later. Environments only grow.
- Every time-valued column gets creation_and_time_generator.get_and_inc(), never a literal or now(),
  so no two rows share a timestamp. Not only the column you sort by today.

## One thing, one unit per test
- Each test checks one thing. Two outcomes to check → two tests.
- A test exercises one unit: the updater, the reader, the creator, or the endpoint.
  The environment (data) and the assertion are as dumb as possible.
- Never use two production units in one test (create with the creator, then check with the reader; update, then read):
  it's slower, and the second unit can hide a problem the first one made. Check the result through the models
  (re-read the row from the session) or the object the unit returned.
- Whole-response assertions build the expected value with the test's own formatter (e.g. format_entity_full)
  from the env row. The formatter converts by itself. It may import production model classes,
  never production conversion logic.

## Filters, validators, sorting, counts
- A filter is tested against an independent Python re-implementation of its rule over the fixture data, compared as
  sets, never a hand-written list of ids. A new filter field updates that re-implementation in the same commit.
- Every field of a filter model gets a test that exercises it.
- Sort and pagination get fixture rows that differ only in the sorted column.
- A validator shared by create and update is tested through both.
- Where the suite counts queries, a new method that loops over a collection pins its count in the same commit (the
  constant's name says where the number comes from); a change that lowers the count lowers the constant.

## Layout
- tests/utils/ is a package of shared helpers, one file per subject (general.py, project.py, ...).
- Each module directory has <module>_test_utils.py (its helpers and initialize_test_environment) and a conftest.py
  that holds only module_env and env.

## Control flow (tests too)
- Explicit checks: len(items) == 0, value is None. Booleans: `if is_ready:`, never `== True` / `is True`.
- Never `value or default`; write `if value is None: value = default`.
- No else after return/raise/break.
