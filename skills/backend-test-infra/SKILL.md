---
name: backend-test-infra
description: Use when writing or reviewing backend tests that touch PostgreSQL, MongoDB, the FastAPI test client, the reverse proxy, RabbitMQ, or Temporal. Defines the integration and API test layers and how to set up each dependency. Complements pytest-conventions.
---

# Backend Test Infrastructure

Applies to code you write or change. Never to unchanged lines.

`pytest-conventions` defines how a test is written. This skill defines **what each layer tests and how its dependencies are set up**. Always follow the project's existing fixtures first: find them in the reference test files listed in the service map, and only add new fixtures when none exist.

**A service's `tests/CLAUDE.md` wins where it differs** (e.g. `services/evermore/tests/CLAUDE.md` defines evermore's inventory test model: package environments, `env`/`session` fixtures, never build rows in a test).

---

## 1. The Two Layers

| | Integration | API |
|---|---|---|
| Calls | The service manager/reader directly (e.g. the entities reader) | The endpoint, through the FastAPI test client |
| Database | Real test database | Real test database |
| Proves | Business logic, queries, ORM behavior, domain exceptions, edge cases | Routing, validation (422), status codes, error-to-status mapping, response shape |
| Typical file | `tests/<module>/test_<what>.py` | `tests/<module>/test_<what>_api.py` (or the project's existing naming) |

- Every new endpoint gets **both** layers.
- Put edge-case depth in the integration layer. The API layer covers success, every validation/error status, and the response shape.
- Unit tests (no I/O) are for pure helpers only.

---

## 2. PostgreSQL (CRUD service)

- Test against **real PostgreSQL**, not SQLite. JSON columns, constraints, `ON CONFLICT`, and case sensitivity behave differently. Use the project's test database (docker-compose service or testcontainers) as found in the reference tests.
- Isolation and data setup: the service's own fixtures, as its `tests/CLAUDE.md` describes (for evermore: one package environment, re-read per test into a session that rolls back). Never rely on rows another test wrote.
- Migrations: if the feature adds one, have one test that applies it on an empty schema (if the project already does this).

## 3. FastAPI test client (API layer)

- Use the project's existing client fixture. If there is none: `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")` for async apps, or `TestClient(app)` for sync ones.
- Override the existing DB dependency (`get_session`) so the API test uses the test's own rolled-back session (for evermore, the `session` fixture): `app.dependency_overrides[get_session] = lambda: session`. Clear the overrides at teardown.
- Assert the status code **and** the body. For errors, assert the exact `detail`.

## 4. MongoDB service

- Prefer a real Mongo (testcontainers or the compose service) when the code relies on indexes, aggregation, or transactions. `mongomock`/`mongomock-motor` is acceptable for simple CRUD, if the project already uses it.
- Isolation: a unique database name per test (or drop the collections at teardown).
- Create the indexes the code relies on inside the fixture, using the app's own index setup function.

## 5. Reverse proxy

- Pure pass-through routes have no tests (exempt).
- Routes with logic (header rewriting, auth, path mapping, aggregation): mock the downstream service at the HTTP boundary (`respx`, or `httpx.MockTransport`), then assert the forwarded request (method, path, headers, body) and the proxied response.

## 6. RabbitMQ

- **Publishing:** patch the publisher where it's looked up (`services.entities.publish_entity_created`), then assert the exact message payload and routing key. Never connect to a real broker in unit or integration tests.
- **Consuming:** call the consumer's handler function directly with a message body built from the schema. Assert its effects (DB state, published follow-up messages), plus ack/requeue behavior for bad messages.
- Test idempotency: delivering the same message twice has no double effect.

## 7. Temporal

- Workflows: `WorkflowEnvironment.start_time_skipping()` from `temporalio.testing`, with a `Worker` registering the workflow and **mocked activities** (functions with the same `@activity.defn(name=...)`). Assert the workflow result and the activities called.
- Activities: test them as normal async functions (integration layer, real DB), or with `ActivityEnvironment` when they use activity context (heartbeats, info).
- Cover retries and timeouts that the spec defines (a mocked activity that fails N times, then succeeds).

---

## 8. Coverage

- Run: `uv run pytest --cov=<package> --cov-report=xml`
- Changed lines only: `uv run diff-cover coverage.xml --compare-branch=<base> --fail-under=100`
- Uncovered changed lines are either tested or listed under `## Coverage exemptions` in `state.md`, one line each: `- path:lines: reason`.
