---
name: grill-with-docs
description: Use in the feature workflow after exploration and before writing the spec. Interviews the user (based on Matt Pocock's grill-me / grill-with-docs) until there is a shared understanding, walking the decision tree in batches of up to 4 related questions, each quoting the user's requirement it is about and carrying a recommended answer. Keeps the requirements verbatim, a coverage checklist and an unknowns list in grill-notes.md, ends with a confirmed readback, and updates the domain glossary and ADRs as it goes.
---

# Grill With Docs

Interview the user until you both understand the feature the same way, **before** anything is planned, so that after the spec is approved the work runs without stopping to ask.

## Inputs
- The feature description.
- `docs/features/<slug>/context.md` (files involved) and `patterns.md` (how similar things are done today), merged from the explorers. Read both first. Each item is marked with how many explorers found it: `3/3`, `2/3`, or `1/3`. **Check every `1/3` item in the code before relying on it**, in a question or a recommendation.
- `docs/CONTEXT.md` (domain glossary) and `docs/adr/` (decision log) if they exist.

## Ground rules
1. **Never ask what the code can answer.** If the answer is in `context.md`, `patterns.md`, or the code, look it up instead. Ask only about intent, behavior, and trade-offs.
2. **Walk the decision tree.** Settle the decisions that others depend on first (e.g. "sync or background job?" before "how does the page show progress?").
3. **Batches of up to 4 related questions** per round, with `AskUserQuestion`. Questions that depend on each other never go in the same batch: the later one waits for the next round.
4. **Quote first.** Every question opens with the requirement it's about, in the user's words:
   > **About R-2** ("if the export takes long, don't block the page"): should the page poll for the result, or should you get a snackbar when it's ready?

   When there's no R-n, quote the code fact instead: "`patterns.md` P-3: entities export uses a Temporal workflow".
5. **Always recommend.** Each question has 2–4 options, and the first option is your recommendation, labeled "(Recommended)", with a one-line reason in its description. Ground recommendations in the existing patterns.
6. **Be concrete.** Ask "When an entity with the same name exists, should create return 409 or overwrite it?", never "How should errors be handled?".
7. **Challenge the language.** If the user uses a term that conflicts with `docs/CONTEXT.md` or the code (e.g. "item" when the code says "entity"), ask which one is meant, and record the answer in the glossary.

## grill-notes.md
Keep `docs/features/<slug>/grill-notes.md` up to date after every round:
```markdown
## Requirements (the user's words, verbatim)
- R-1 "<exactly what the user wrote>"
- R-2 "<...>"
## Unknowns
- U-1 <question or assumption> → status: open | decided: <answer> | assumed: <assumption>
## Decisions
- D-1 <decision> (from U-1, about R-2)
## Coverage
Covered: behavior, data · Left: API, errors, edge cases, UI states, git
```
- **Requirements** are copied word for word from the feature description and the user's answers. Never paraphrase them; a new requirement in an answer gets the next R-n.
- **Unknowns:** before every round, add every assumption you are silently making. Each one becomes a decision (the user confirmed it) or a question before the spec. The grill ends only when **no unknown is open or assumed**.

## Coverage checklist
Go through every item and mark it covered or N/A. Group related items into one round. After each round, write `Covered: … · Left: …` in the notes and show that line to the user.

- [ ] Behavior: main user flow, step by step
- [ ] Users and permissions: who can do it, and what others see
- [ ] Data: new or changed models, fields, types, nullability, defaults, uniqueness, migration of existing rows
- [ ] API contract: endpoints, methods, request/response shapes, status codes, pagination, filtering
- [ ] Reverse proxy: new or changed routes
- [ ] Errors: every failure mode and what the user sees for it
- [ ] Edge cases: empty, huge, duplicate, concurrent, deleted-in-between, invalid input
- [ ] Cross-service effects: RabbitMQ messages (schema, who consumes them), Temporal workflows (retries, timeouts, idempotency)
- [ ] UI states: views, dialogs, loading / empty / error / success, tooltips, where it lives in navigation
- [ ] Patterns: for every inconsistency `I-n` in `patterns.md`, which side to follow, and confirmation of every pattern that will be reused
- [ ] Non-goals: what explicitly won't be built
- [ ] Backward compatibility: existing clients, existing data, other services' consumers
- [ ] Tests: anything special beyond the defaults. Which **user journeys** deserve a browser test (Playwright, mocked backend)? Recommend one happy path per new journey plus its main failure.
- [ ] Missing tooling from `context.md`: add it as part of this feature, or skip that check?
- [ ] Git: anything beyond the defaults (one branch per BTRC-n, finished by `finish_branch.py`)

## Readback
When no unknown is left, write a **readback** of 5–8 bullets: what will be built, what won't, and the riskiest decision, each pointing to the R-n it comes from. Ask one final question: "Is this what you want?" with the options "Yes, write the spec (Recommended)" and "No, I'll correct it". Loop until the user confirms.

## Docs updates
- New or clarified domain terms go in `docs/CONTEXT.md` (create it if missing): `**Term**: definition. Code name: X.`
- Decisions that will matter beyond this feature (a new convention, an architecture choice) get a short ADR in `docs/adr/NNNN-<title>.md`: context, decision, consequences.
- Everything else stays in `grill-notes.md`.

## Output
- `docs/features/<slug>/grill-notes.md` with the requirements verbatim, every unknown decided, and the coverage line showing nothing left.
- Any updates to `docs/CONTEXT.md` and `docs/adr/`.
