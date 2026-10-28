# Spec: <feature name>

Status: DRAFT | APPROVED (<date>)

## 1. Goal
<2–3 sentences: what the user gets and why.>

## 2. Non-goals
- <explicitly out of scope>

## 3. Requirements
| ID | Requirement | Acceptance criteria | From |
|----|-------------|---------------------|------|
| REQ-1 | | | D-1 |

## 4. Edge cases
| ID | Situation | Expected behavior | From |
|----|-----------|-------------------|------|
| EC-1 | | | |

## 5. API contracts
### <METHOD> <path> (service: <name>)
- Request: <fields, types, required/optional>
- Response <status>: <fields, types>
- Errors: <status> → <exception> → <frontend behavior>
- Proxy route: <path on proxy> → <service path>

## 6. Data changes
- PostgreSQL (SQLModel): <model, fields, constraints, indexes>; migration: <what happens to existing rows>
- MongoDB: <collection, document shape, indexes>

## 7. Async
- RabbitMQ: <exchange/queue, message schema, publisher, consumers, idempotency, ack/requeue>
- Temporal: <workflow, activities, task queue, timeouts, retries, idempotency>

## 8. Frontend
- Views/components: <name — purpose — parent>
- States: loading / empty / error / success for each async action
- Types (`src/models/`): <TS interfaces mirroring the schemas>
- Tooltips: <where `EasyToolTip` + `mdi-information` is needed>

## 9. Decisions
- D-1 <decision> (grill U-n)

## 10. Patterns to follow
- <area> → P-n (`reference file`)

## 11. Git
- Branch: <Branch from state.md> · Base: <Base from state.md>
- Finish: `finish_branch.py` (one commit titled from the `# Spec: <feature name>` heading above, rebase, push, pipeline, containers down, worktree removed)

## 12. Open questions
<must be empty before approval>
