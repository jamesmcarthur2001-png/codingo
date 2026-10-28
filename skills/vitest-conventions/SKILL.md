---
name: vitest-conventions
description: Use when writing, reviewing, or setting up frontend tests with Vitest for Vue 3 + Vuetify + TypeScript, covering both component tests (Vue Test Utils) and frontend integration tests (a whole view with real store, router, and MSW-mocked network). Defines layers, file layout, naming, AAA structure, mocking boundaries, and coverage.
---

# Vitest Frontend Testing Conventions

Applies to code you write or change. Never to unchanged lines.

The frontend counterpart of `pytest-conventions`. It covers two Vitest layers:

| Layer | What is mounted | What is mocked | Detailed rules |
|---|---|---|---|
| **fe-component** | One component, with its real children | API client module (`vi.mock`), store actions (`createTestingPinia`) | `references/component-tests.md` |
| **fe-integration** | A whole view or feature, with real children, real Pinia, real router, real API client | **Only the network**, through MSW | `references/integration-tests.md` |
| fe-unit | Pure utils/composables without DOM | Nothing (or the clock) | this file only |

Browser tests (real browser, mocked backend) are a separate layer. See `browser-test-conventions`.

**Read the reference file for the layer you are writing before you write it.** Test code also follows `vue-conventions` (explicit checks, named constants, descriptive names). Reviewers use `references/checklist.md`.

---

## 1. Core Principles (all layers)

1. **Test behavior through the public interface:** props, emitted events, slots, rendered output, and user interaction. Never assert internal refs, call component methods, or reach into `wrapper.vm`. Logic that needs deep testing goes into a util with its own fe-unit test.
2. **Arrange-Act-Assert, visibly:** separate the three blocks with single blank lines. No `// Arrange` comments, and no comments in tests unless they document a non-obvious workaround.
3. **One behavior per test:** multiple `expect`s only when they check the same outcome.
4. **No loops or conditionals in tests:** use `it.each` for variations.
5. **DAMP over DRY:** a test reads top to bottom. Factories and mount helpers are fine; hiding the arrange step behind clever abstractions isn't.
6. **Mock at the boundary you own:** the API client (component layer) or the network (integration layer), plus timers and browser APIs. Never mock the unit under test. Don't stub child components by default.
7. **Isolation:** a fresh Pinia per test, a fresh router per test, mocks restored after each test (`restoreMocks: true` in config), and MSW handlers reset after each test. Tests pass in any order.
8. **Interact like a user:** `await wrapper.get(...).trigger('click')` and `await input.setValue(...)`. Always `await` them, because Vue updates the DOM asynchronously.
9. **Wait for real things:** `await flushPromises()` after anything that triggers network work. Never use `setTimeout`/sleep waits.
10. **No snapshot-only tests:** a snapshot never replaces asserting the behavior.

---

## 2. Files & Layout

```
tests/
  unit/<mirror of src path>/<Name>.spec.ts            # fe-component and fe-unit
  integration/<feature>/<flow>.spec.ts                # fe-integration
  e2e/...                                             # browser (see browser-test-conventions)
  mocks/
    factories/<entity>.ts      # typed test-data factories (shared by every layer)
    handlers/<domain>.ts       # MSW happy-path handlers per backend domain
    handlers/index.ts          # combines all handlers
    server.ts                  # setupServer(...handlers)
  utils/
    mount.ts                   # mountWithPlugins (Vuetify + router + pinia options)
  setup.ts                     # Vitest setup file (MSW lifecycle, ResizeObserver)
```

*If the project already has a different layout when Vitest is set up, follow that one and update this section.*

Internal file order (as in pytest-conventions): imports, then module-level mocks (`vi.mock`, which is hoisted anyway), then local helpers/constants, then one `describe('<UnitName>')` containing the tests.

---

## 3. Naming

- `describe('<ComponentName>')` for component tests, `describe('<Feature>: <flow>')` for integration tests.
- `it('<expected behavior> when <condition>')`, as a plain sentence about observable behavior:
  - `it('shows an error message when loading entities fails')`
  - `it('emits update with the entity id when the save button is clicked')`
  - `it('lists the created entity after the create dialog is submitted')`
- The `it(...)` string must match the "Test name" column of `test-plan.md` exactly. A hook enforces this.

---

## 4. Test Data

- Build every object through a typed factory from `tests/mocks/factories/`: `makeEntity({ name: 'Pump' })`. Factories return the **API types from `src/models/`**, so a contract change breaks the factories at compile time.
- Defaults are valid and realistic. Each test overrides only the fields that matter to it, so the arrange step shows what the test is about.
- The same factories feed MSW handlers, `vi.mock` return values, and Playwright fixtures.

---

## 5. Selectors

Vue Test Utils has no accessibility queries, so:
- Select elements by `data-testid` (`wrapper.get('[data-testid="save-entity-button"]')`). Never select by Vuetify classes (`.v-btn`), tag structure, or ids.
- Add `data-testid` to the component under test where needed. Name it `<what>-<kind>`: `entity-name-input`, `save-entity-button`, `entities-empty-state`.
- Assert on **what the user sees**: text (`toContain('Pump')`), visibility, `disabled`/`aria-*` attributes, and emitted events.
- Use `get()` when the element must exist (it fails clearly), and `find(...).exists()` only to assert that something is absent.

---

## 6. Coverage

- New and changed frontend code needs ~100% changed-line coverage from **fe-component + fe-integration + fe-unit** together. Browser tests don't count toward coverage.
- Prefer covering a line through a behavior test over writing a test only to hit the line. If a line can only be covered by testing implementation details, extract that logic into a util and unit-test it.

---

## 7. Setup (one time, when Vitest is added)

```bash
npm install -D vitest @vue/test-utils jsdom @vitest/coverage-v8 resize-observer-polyfill msw @pinia/testing
```

`vitest.config.ts`:
```ts
import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(viteConfig, defineConfig({
  test: {
    environment: 'jsdom',
    include: ['tests/unit/**/*.spec.ts', 'tests/integration/**/*.spec.ts'],
    setupFiles: ['tests/setup.ts'],
    restoreMocks: true,
    unstubGlobals: true,
    server: { deps: { inline: ['vuetify'] } },
    coverage: { provider: 'v8', reporter: ['text', 'cobertura'], include: ['src/**'] },
  },
}))
```

`tests/setup.ts`:
```ts
import ResizeObserver from 'resize-observer-polyfill'
import { afterAll, afterEach, beforeAll } from 'vitest'

import { server } from './mocks/server'

globalThis.ResizeObserver = ResizeObserver

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
```
`onUnhandledRequest: 'error'` makes any request without a handler fail the test. In component tests, where the API module is mocked, this also catches leaks to the real network.

`tests/utils/mount.ts` exports `mountWithPlugins(component, options)`. It creates Vuetify with the app's **real** theme config (so semantic theme keys exist), passes `global.plugins` (Vuetify, plus the router/pinia given in the options), and sets `global.stubs: { teleport: true }`. Vuetify dialogs, menus, and snackbars teleport into `document.body`, so without this stub their content is outside the wrapper and `wrapper.get(...)` can't find it.

Run everything: `npx vitest run --coverage`. Changed lines only: `diff-cover coverage/cobertura-coverage.xml --compare-branch=<base> --fail-under=100`.

**jsdom limits:** Vuetify recommends a real browser for components that depend on layout, overlays, or real events (menus, `v-select` dropdowns, tooltips, virtual scrolling). If such a behavior can't be tested reliably in jsdom, test it in a browser test instead of fighting jsdom, and say so in that row's "What it checks" column in `test-plan.md`.
