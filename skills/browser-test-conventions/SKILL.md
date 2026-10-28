---
name: browser-test-conventions
description: Use when writing, reviewing, or setting up browser tests with Playwright for the Vue/Vuetify frontend. Every backend call is mocked with page.route and typed factory data. Covers which user journeys get a browser test, the mock fixture that fails on unmocked requests, locator priority, web-first assertions, isolation, naming, and config.
---

# Browser Test Conventions (Playwright, mocked backend)

Applies to code you write or change. Never to unchanged lines.

Browser tests run the **real frontend in a real browser** (Vite dev server + Chromium) and click through it the way a user does. **The backend is always mocked**: every API request is answered from typed factory data, so tests are fast, deterministic, and never depend on running services.

They complement Vitest (`vitest-conventions`). Vitest covers details, edge cases, and coverage. Browser tests prove that **the critical journeys work in a real browser**, with real layout, overlays, focus, routing, and events that jsdom can't fully reproduce.

---

## 1. What Gets a Browser Test

- **One test per new or changed user journey** from the spec: the happy path (e.g. "user creates an entity and sees it in the list").
- **One test per journey-level failure** the spec defines (e.g. "user sees an error when the backend rejects the entity").
- Behavior that is **unreliable in jsdom**: Vuetify menus and selects, dialogs and focus, tooltips, virtual scrolling, drag and drop, file upload, real navigation and back buttons.
- **Not** every edge case or validation rule. Those belong in fe-integration/fe-component tests. Browser tests are few and high-value.

---

## 2. Principles (shared with pytest-conventions and vitest-conventions)

1. **Test what the user sees and does:** no assertions on CSS classes, component internals, or the store.
2. **Arrange-Act-Assert:** arrange the mocks, act by navigating and interacting, assert the visible result. Use `test.step('...')` to name the phases of a longer journey.
3. **Isolation:** every test gets a fresh browser context (Playwright's default). No test depends on another test or on run order. Shared setup goes in fixtures, not in earlier tests.
4. **DAMP:** a test reads as the journey it describes. Helpers are fine; hidden magic isn't.
5. **Deterministic data:** only factory data with fixed values. Never real backend data, `Math.random()`, or the current date without freezing it (`page.clock.setFixedTime(...)`).

---

## 3. Mocking the Backend

### 3.1 The `api` fixture (required)
All tests import `test`/`expect` from `tests/e2e/fixtures.ts`, never from `@playwright/test` directly. That module defines:

- An **auto fixture** that registers a catch-all route for the API prefix **first**. Playwright runs the most recently registered matching route first, so this catch-all only runs when no specific mock handled the request. It answers `501`, records the URL, and **fails the test at teardown** if any request was unmocked.
- An `api` fixture with typed helpers to register mocks: `api.mock(method, path, response)` and `api.mockError(method, path, status, detail)`.

```ts
import { test as base, expect } from '@playwright/test'

const API_PATH_PREFIX = '/api' // the proxy prefix from the service map

type ApiMocks = {
  mock: (method: string, path: string, json: unknown, status?: number) => Promise<void>
  mockError: (method: string, path: string, status: number, detail: string) => Promise<void>
}

export const test = base.extend<{ api: ApiMocks; failOnUnmockedRequests: void }>({
  failOnUnmockedRequests: [async ({ page }, use) => {
    const unmockedRequests: string[] = []
    await page.route((url) => url.pathname.startsWith(`${API_PATH_PREFIX}/`), async (route) => {
      unmockedRequests.push(`${route.request().method()} ${route.request().url()}`)
      await route.fulfill({ status: 501, json: { detail: 'Unmocked request in browser test' } })
    })
    await use()
    expect(unmockedRequests, 'every API request must be mocked').toEqual([])
  }, { auto: true }],

  api: async ({ page }, use) => {
    const register = async (method: string, path: string, status: number, json: unknown) => {
      await page.route((url) => url.pathname === `${API_PATH_PREFIX}${path}`, async (route) => {
        if (route.request().method() !== method) {
          await route.fallback()
          return
        }
        await route.fulfill({ status, json })
      })
    }
    await use({
      mock: (method, path, json, status = 200) => register(method, path, status, json),
      mockError: (method, path, status, detail) => register(method, path, status, { detail }),
    })
  },
})

export { expect }
```

### 3.2 Rules
- Mock data comes from the **same typed factories** as Vitest (`tests/mocks/factories/`), so contract changes break browser tests at compile time too.
- Paths, methods, status codes, and payload shapes match `spec.md` §5 exactly.
- **Validate mutation payloads in the route handler**, like the backend would, instead of asserting on the request afterwards. For example, return `422` when a required field is missing. A wrong payload then surfaces as a visible error and fails the test on what the user sees.
- Register mocks **before** `page.goto(...)`.
- Mocks match on the exact pathname, so query strings (`?page=2`) don't break matching. When a test needs different responses per query, register a handler that reads `new URL(route.request().url()).searchParams`.
- For stateful journeys (create, then list), keep the state in a local array inside the handler: POST pushes a factory object, and GET returns the array.
- Set `serviceWorkers: 'block'` in the config, so a service worker can't bypass `page.route`.
- Never call real services, staging, or third-party URLs.

---

## 4. Locators

In priority order (the Playwright and Testing Library guidance agree on this):
1. `page.getByRole('button', { name: 'Save' })`: roles plus accessible names, the default choice
2. `page.getByLabel('Name')`: form fields (Vuetify `label` props render real labels)
3. `page.getByPlaceholder(...)` / `page.getByText(...)`: non-interactive content
4. `page.getByTestId('entities-table')`: last resort, when the element has no accessible role or name (e.g. some Vuetify composites). This reuses the same `data-testid` values as Vitest.

- Narrow scope with chaining and filters: `page.getByRole('row').filter({ hasText: 'Pump' }).getByRole('button', { name: 'Delete' })`.
- Never use CSS classes (`.v-btn`), XPath, or `nth()` positions unless nothing else is possible.
- When unsure what role Vuetify renders, run `npx playwright codegen` against the dev server and copy its locator.

---

## 5. Assertions & Waiting

- Use **web-first assertions only:** `await expect(locator).toBeVisible()`, `.toHaveText()`, `.toContainText()`, `.toHaveCount()`, `.toBeDisabled()`, `await expect(page).toHaveURL(...)`. They retry until the condition is met.
- Never `expect(await locator.isVisible()).toBe(true)`. It checks once and doesn't wait.
- Never use `page.waitForTimeout(...)` or `waitUntil: 'networkidle'`. Wait for the visible result instead.
- `await` every Playwright call. Enable `@typescript-eslint/no-floating-promises` for `tests/e2e`.
- Use `expect.soft` only when checking several independent fields of one result.

---

## 6. Files & Naming

```
tests/e2e/
  fixtures.ts                         # test/expect with the api + unmocked-request fixtures
  <feature>/<journey>.spec.ts         # e.g. entities/create-entity.spec.ts
playwright.config.ts
```
- `test.describe('<Feature>')` per file, and `test('<user goal and visible outcome>')`:
  - `test('user creates an entity and sees it in the list')`
  - `test('user sees an error message when the backend rejects the new entity')`
- The `test(...)` string must match the "Test name" column of `test-plan.md` exactly. A hook enforces this.

### Example
```ts
import { makeEntity } from '../../mocks/factories/entity'
import { expect, test } from '../fixtures'

test.describe('Entities', () => {
  test('user creates an entity and sees it in the list', async ({ page, api }) => {
    await api.mock('GET', '/entities', [makeEntity({ name: 'Valve' })])
    await api.mock('POST', '/entities', makeEntity({ name: 'Pump' }), 201)
    await page.goto('/entities')

    await page.getByRole('button', { name: 'New entity' }).click()
    await page.getByLabel('Name').fill('Pump')
    await page.getByRole('button', { name: 'Save' }).click()

    await expect(page.getByRole('row').filter({ hasText: 'Pump' })).toBeVisible()
  })
})
```

---

## 7. Setup (one time)

```bash
npm install -D @playwright/test
```

```bash
npx playwright install chromium --with-deps
```

`playwright.config.ts`:
```ts
import { defineConfig, devices } from '@playwright/test'

const DEV_SERVER_PORT = 5173

export default defineConfig({
  testDir: 'tests/e2e',
  fullyParallel: true,
  forbidOnly: process.env.CI !== undefined,
  retries: process.env.CI !== undefined ? 2 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://localhost:${DEV_SERVER_PORT}`,
    trace: 'on-first-retry',
    serviceWorkers: 'block',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run dev',
    url: `http://localhost:${DEV_SERVER_PORT}`,
    reuseExistingServer: process.env.CI === undefined,
  },
})
```
- Chromium only by default. Cross-browser runs have diminishing returns; add Firefox/WebKit projects only if the spec requires it.
- Exclude `tests/e2e/**` from the Vitest `include`.
- Run with `npx playwright test`. Debug with `npx playwright test --debug` or `--ui`. Open traces with `npx playwright show-report`.

Reviewers use `references/checklist.md`.
