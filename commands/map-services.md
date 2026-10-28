---
description: "Scan the monorepo and write (or refresh) the project's service-map skill: services, routes, data, RabbitMQ, Temporal, and commands."
argument-hint: "[optional: path to the monorepo root]"
---

# Map the services

Create or refresh `.claude/skills/service-map/SKILL.md` in the monorepo root (`$ARGUMENTS`, default: the current directory). It's a project skill, so it should be committed and shared with the team. The `/feature` workflow reads it in every run.

## Rules
- Write facts only. Every filled cell must come from a file you read. Cite the reference file path.
- When something can't be determined from the code, write `TODO (unknown: <what you looked for>)`. Never guess.
- Don't change any application code.
- If the file already exists, update it in place and keep any hand-written corrections unless the code clearly contradicts them (list those for the user).

## Steps
1. Find every service: look for `pyproject.toml`, `package.json`, `Dockerfile`, and `docker-compose*.yml` files. For each service, record its path, stack, and run/test commands (from `pyproject.toml`, `package.json` scripts, the Makefile, CI config, or the README).
2. Reverse proxy: find where routes are declared and how a request is forwarded. Pick one clean route as the reference.
3. CRUD service: find the SQLModel models, the service managers/readers (e.g. the entities reader), session handling, and migrations. Pick reference files.
4. Mongo service: find the client setup, collection access, and index definitions.
5. RabbitMQ: search for `pika`, `aio_pika`, `kombu`, `faststream`, and `exchange`/`queue` declarations.
6. Temporal: search for `@workflow.defn`, `@activity.defn`, `Worker(`, and `task_queue`.
7. Frontend: find the API client layer, the `src/models/` types, the stores, and where `handleNetworkError`, `EasyToolTip`, and the loadable resource component live.
8. Tests: find the existing integration tests (service manager/reader) and API tests (test client), and pick one reference file of each. Do the same for frontend tests: component, integration (MSW), and browser (Playwright). Check whether `pytest-cov`, `diff-cover`, `vitest`, `@vitest/coverage-v8`, `@vue/test-utils`, `msw`, `@pinia/testing`, and `@playwright/test` are installed, and find the API path prefix the frontend uses (e.g. `/api`). Mark missing ones as `MISSING: <package>` in the commands table.
9. Write the file using the template below: keep its frontmatter and section structure, and replace every `TODO` you can.
10. Report to the user what you filled, what is still `TODO`, any `MISSING` tools, and any inconsistencies you found (e.g. two different ways of declaring proxy routes).

## Template

````markdown
---
name: service-map
description: Use whenever a task touches more than one service, adds an endpoint or proxy route, publishes or consumes RabbitMQ messages, adds a Temporal workflow, or needs the run/test commands of a service. Describes every service in the monorepo and how they communicate.
---

# Service Map

The architecture of the monorepo: which service owns what, how requests and messages flow, and how to run and test each service.

---

## 1. Services

| Service | Path | Stack | Owns | Run | Test |
|---|---|---|---|---|---|
| Frontend | `TODO` | Vue 3, Vuetify, TypeScript | UI | `TODO` | `TODO` |
| Reverse proxy | `TODO` | FastAPI | Routing every frontend request to a service | `TODO` | `TODO` |
| CRUD service | `TODO` | FastAPI, PostgreSQL, SQLAlchemy, SQLModel | Entities and other relational data | `TODO` | `TODO` |
| Mongo service | `TODO` | FastAPI, MongoDB | `TODO` | `TODO` | `TODO` |
| `TODO` (other services) | `TODO` | FastAPI | `TODO` | `TODO` | `TODO` |

---

## 2. Request Flow

```
Browser → Frontend (Vue) → Reverse proxy → <service> → Postgres / Mongo
                                              ↘ RabbitMQ → consumers
                                              ↘ Temporal → workflows/activities
```

### Adding an endpoint end to end
1. Service: router file `TODO`, schema file `TODO`, service manager/reader `TODO`.
2. Register the router in `TODO`.
3. Reverse proxy: add the route in `TODO`, following `TODO (reference route)`.
4. Frontend: API client in `TODO`, types in `src/models/`.

---

## 3. Data Layer

### CRUD service (PostgreSQL)
- Models: `TODO` (SQLModel). Reference model: `TODO`.
- Service managers/readers: `TODO` (e.g. the entities reader). Reference: `TODO`.
- Sessions and transactions: `TODO` (how a session is obtained, who commits).
- Migrations: `TODO` (tool, command, where they live).

### Mongo service
- Client and database access: `TODO`. Reference repository/collection module: `TODO`.
- Indexes are defined in: `TODO`.

---

## 4. Messaging (RabbitMQ)

| Exchange / queue | Publisher | Consumer | Message schema |
|---|---|---|---|
| `TODO` | `TODO` | `TODO` | `TODO` |

- Publishing helper: `TODO`. Consumer base/pattern: `TODO`.
- Ack/requeue/dead-letter policy: `TODO`.

---

## 5. Workflows (Temporal)

| Workflow | Task queue | Worker location | Activities |
|---|---|---|---|
| `TODO` | `TODO` | `TODO` | `TODO` |

- Workflow code must stay deterministic: no `datetime.now()`, randomness, network, or DB access inside workflow code. Those belong in activities.
- Activity timeout and retry conventions: `TODO`.

---

## 6. Cross-Service Contracts

- Service-to-service calls go through: `TODO` (direct HTTP client / proxy / shared lib).
- Shared schemas or libraries: `TODO`.
- Auth and headers forwarded by the proxy: `TODO`.

---

## 7. Commands Cheat Sheet

| Task | Command |
|---|---|
| Install backend deps | `uv sync` (inside the service directory) |
| Backend tests + coverage | `uv run pytest --cov=<package> --cov-report=xml` |
| Coverage of changed lines | `uv run diff-cover coverage.xml --compare-branch=<base> --fail-under=100` |
| Types | `uv run mypy --strict <package>` |
| Frontend tests + coverage | `TODO` (e.g. `npx vitest run --coverage`, see `vitest-conventions`) |
| Browser tests | `TODO` (e.g. `npx playwright test`, see `browser-test-conventions`) |
| Frontend API path prefix | `TODO` (e.g. `/api`; used by MSW handlers and the Playwright `api` fixture) |
| Frontend type check | `TODO` (e.g. `npx vue-tsc --noEmit`) |

---

## 8. Reference Test Files

- Integration test (service manager/reader): `TODO`
- API test (test client): `TODO`
- Frontend component test: `TODO` (none yet if Vitest isn't set up)
- Frontend integration test: `TODO`
- Browser test: `TODO` (none yet if Playwright isn't set up)
````
