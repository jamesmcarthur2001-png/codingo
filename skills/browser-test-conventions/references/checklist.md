# Browser Test Conventions Checklist

Run this per changed Playwright file. Every item must be answered ✅, ❌ (with `file:line`), or N/A.

## Scope
- [ ] BR-01 Each test covers a user journey or journey-level failure from the spec, not a detail that a Vitest test should cover
- [ ] BR-02 Behavior that is unreliable in jsdom (menus, selects, dialogs and focus, navigation) is covered here when the feature has it

## Mocking
- [ ] BR-10 Imports `test`/`expect` from `tests/e2e/fixtures.ts`, so the unmocked-request guard is active
- [ ] BR-11 Every API call the journey makes is mocked through the `api` fixture, before `page.goto`
- [ ] BR-12 Mock data comes from the typed factories in `tests/mocks/factories/`
- [ ] BR-13 Mocked paths, methods, statuses, and shapes match `spec.md` §5
- [ ] BR-14 Mutation mocks validate the payload (or the journey's visible result proves the right payload was sent). No request assertions.
- [ ] BR-15 No real services, staging, or third-party URLs, and no unfrozen dates or randomness

## Locators & assertions
- [ ] BR-20 Locator priority is followed: role+name, then label, then text/placeholder, then test id (last resort). No CSS classes, XPath, or `nth()` without a reason.
- [ ] BR-21 Only web-first assertions (`await expect(locator).toBeVisible()` etc.), never `expect(await x.isVisible())`
- [ ] BR-22 No `waitForTimeout`, no `networkidle`, and every Playwright call is awaited
- [ ] BR-23 Each test ends by asserting the visible outcome of the journey

## Structure
- [ ] BR-30 File is at `tests/e2e/<feature>/<journey>.spec.ts`, with one `test.describe('<Feature>')`
- [ ] BR-31 `test(...)` names describe the user goal and outcome, and match `test-plan.md` exactly
- [ ] BR-32 Arrange (mocks), Act (navigate and interact), and Assert are clear, with `test.step` for long journeys
- [ ] BR-33 Tests are independent, with no reliance on order or on state from another test
