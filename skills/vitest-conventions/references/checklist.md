# Vitest Conventions Checklist

Run this per changed frontend Vitest file. Every item must be answered ✅, ❌ (with `file:line`), or N/A.

## All Vitest layers
- [ ] VT-01 File is in the right place for its layer (`tests/unit/<mirror>` for component/unit, `tests/integration/<feature>/` for integration) and ends in `.spec.ts`
- [ ] VT-02 One `describe` named after the unit (component) or `<Feature>: <flow>` (integration)
- [ ] VT-03 `it(...)` strings read as "<expected behavior> when <condition>" and match `test-plan.md` exactly
- [ ] VT-04 Arrange / Act / Assert separated by blank lines, with no comments
- [ ] VT-05 One behavior per test, with no loops or conditionals (`it.each` for variations)
- [ ] VT-06 Test data comes from typed factories in `tests/mocks/factories/`, overriding only the relevant fields
- [ ] VT-07 Elements selected by `data-testid`, never by Vuetify classes or DOM structure
- [ ] VT-08 Every `trigger`/`setValue`/`setProps` is awaited, and `flushPromises()` is used after network work (no sleeps)
- [ ] VT-09 No access to `wrapper.vm` internals and no calls to component methods
- [ ] VT-10 Every test has a meaningful assertion on visible output or emitted events (no snapshot-only tests, no `expect(true)`, not just "a mock was called")
- [ ] VT-11 Fresh Pinia/router per test, and no shared mutable state between tests
- [ ] VT-12 Debounce tests use fake timers and the component's named debounce constant
- [ ] VT-13 Explicit checks and named constants per `vue-conventions` inside test code

## Component tests
- [ ] VT-20 Uses `mount` (via `mountWithPlugins`), not `shallowMount`. Any stub is justified.
- [ ] VT-21 API is mocked at the app's API client module (`vi.mock('@/api/...')`), not at axios/fetch
- [ ] VT-22 Store uses `createTestingPinia({ createSpy: vi.fn })`, and action calls are asserted as the component's contract
- [ ] VT-23 Props variations, slots, emits (exact payloads), and loading/error/empty states are covered where they exist

## Integration tests
- [ ] VT-30 Mounts the real view with a real Pinia (actions not stubbed) and a real memory-history router
- [ ] VT-31 No `vi.mock` of app modules. Only the network is mocked, via MSW.
- [ ] VT-32 Per-test scenarios use `server.use(...)`, and mutation handlers validate the payload like the backend
- [ ] VT-33 No assertions on request details for requests with visible effects
- [ ] VT-34 Handler paths and payloads match `spec.md` §5
- [ ] VT-35 Main flow, every specified network failure, empty data, and frontend `EC-n` are covered

## Coverage
- [ ] VT-40 New code has ~100% changed-line coverage from the Vitest layers
