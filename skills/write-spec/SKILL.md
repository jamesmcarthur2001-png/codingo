---
name: write-spec
description: Use in the feature workflow after the grill. Turns context.md, patterns.md and grill-notes.md into spec.md and plan.md (2–4 slices, each with the files it may touch), which the user approves at the single gate before autonomous implementation.
---

# Write Spec & Plan

Produce `spec.md` and `plan.md` in `docs/features/<ticket>/` from the templates in this skill's `templates/` folder. After the user approves them, nobody asks the user anything again, so the spec must be complete.

## Preconditions (stop if any one fails)
- `patterns.md` exists. If not, run the explorer first.
- `grill-notes.md` has no unknown that is `open` or `assumed`.

## Writing `spec.md`
- Use `templates/spec.md`. Fill every section, or write `N/A: <why>`. Never delete a section.
- **IDs:** requirements are `REQ-1…`, edge cases `EC-1…`, decisions `D-1…` (copied from grill-notes). Every requirement has testable acceptance criteria: "returns 404 with `EntityNotFoundError` detail", not "handles missing entities".
- **Contracts are exact:** field names, types, nullability, status codes, message schemas. The TS types must mirror the Pydantic/SQLModel schemas field for field.
- **Every decision is traceable:** each `REQ`/`EC` cites the `D-n` it comes from, when it comes from a decision.
- **Mockups:** when `docs/features/<ticket>/mockups/` holds approved mockups (see `html-mockups`), link each one from the requirement it shows: `REQ-2 … (look: [mockups/entity-export-dialog.html](mockups/entity-export-dialog.html))`.
- **Open questions must be empty.** If you discover a new unknown while writing, stop and go back to the grill for it.

## Writing `plan.md`
- Use `templates/plan.md`. `scripts/scope_check.py` parses it, so keep its format exactly.
- **2–4 slices**, each a `## Slice <n>: <name>` header with no other headers inside it.
- Each slice starts with `Files:` and one `` - `path` `` bullet per file it may touch (repo-relative; a folder ending in `/` or a glob is allowed, where `*` stays inside one folder and `**` crosses folders). `check_slice.py` fails on any changed file not listed in slices 1..n.
- Order slices by dependency: model/migration, then service manager/reader, then API route, then proxy route, then frontend types and client, then components/views. Async pieces (RabbitMQ, Temporal) come right after the code they depend on.
- Every slice lists: covered `REQ` IDs, **the pattern it follows (`P-n` plus a reference file)**, its tasks, and a verify command from the service map.
- A slice that follows no existing pattern says `Pattern: NEW, because <reason>`, so the user sees it at the gate.
- Tests aren't in the plan. They're planned later in `test-plan.md`, whose File column is also allowed scope. Test helpers that aren't test files (conftest, environment builders, factories, MSW handlers) go in the last slice's `Files:`.
- No per-task commits: `finish_branch.py` commits once at the end.

## Self-check before presenting
Go through this list and fix anything that fails:
- [ ] Every `REQ` appears in at least one slice
- [ ] Every slice has a `Files:` list and cites a `P-n` or explains `NEW`
- [ ] Every inconsistency `I-n` from `patterns.md` is resolved by a decision
- [ ] Every error in the API contract has a status code and a frontend behavior
- [ ] "Open questions" is empty
- [ ] Nothing in the spec contradicts `grill-notes.md`

## Presenting for approval
Show the user a short summary: goal, number of REQs/ECs/slices, every `NEW` pattern, and the riskiest decision. Point them to the two files. Then ask with `AskUserQuestion`: "Approve the spec and plan?" with the options "Approve and start (Recommended)" and "I have changes". On changes, edit the files and ask again.
