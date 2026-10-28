# Component Tests (Vitest + Vue Test Utils)

A component test mounts **one component** and checks its contract: given these props, slots, and store state, it renders this, and when the user does X, it emits or calls Y.

## 1. What to cover per component
- [ ] **Rendering from props:** each meaningful variation, via `it.each`
- [ ] **Slots:** provided slot content renders in the right place
- [ ] **Emits:** each event fires with the exact payload, in response to the user action that should trigger it
- [ ] **User interaction:** clicks, typing, and keyboard behavior that change the DOM
- [ ] **Async actions:** a loading indicator while pending, the success result, the error path through `handleNetworkError`, and the empty state, with the API module mocked
- [ ] **Validation:** invalid input blocks submission and shows the message
- [ ] **Debounce:** `vi.useFakeTimers()`, then advance by the component's **named** debounce constant (import it from the component's `<script lang="ts">` block), never by a magic number
- [ ] **Dialog content components:** confirm and cancel emit the right events (the `v-dialog` wrapper belongs to the parent)

## 2. Mounting rules
- Overlays (`v-dialog`, `v-menu`, `v-snackbar`) render inline because `mountWithPlugins` stubs `teleport`. Don't query `document.body` for them.
- Use `mount` (through `mountWithPlugins`), **not `shallowMount`**. Real children make the test resemble real use. Shallow rendering hides integration bugs and doesn't render slots.
- Stub a child only when it does work the test doesn't need, such as its own network calls or heavy measuring directives. Stub it by name in `global.stubs` and say why in the test plan.
- Store: `createTestingPinia({ createSpy: vi.fn, initialState: { entities: { items: [makeEntity()] } } })`. Actions are stubbed by default. Assert that the component **called the action with the right arguments** (that is its contract), and test the action itself in a store unit test.
- Router: if the component uses `useRouter`/`RouterLink`, give it a real router with `createRouter({ history: createMemoryHistory(), routes })` and `await router.isReady()` before mounting. Assert `router.currentRoute.value` after navigation.

## 3. Mocking the API in component tests
- Mock the project's API client module, not `axios`/`fetch`: `vi.mock('@/api/entities')`, then `vi.mocked(fetchEntities).mockResolvedValue([makeEntity()])`.
- For errors: `mockRejectedValue(new ApiError(...))`, using the same error shape the real client throws.
- Asserting that the API function was called with specific arguments is acceptable **only** when the call itself is the behavior (e.g. "saves with the edited name"), and always together with the visible result.

## 4. Async rules
- `await` every `trigger`, `setValue`, and `setProps`.
- After an action that starts network work: `await flushPromises()`, then assert.
- To assert a loading state, resolve the mock manually so the pending state is observable:
  ```ts
  let resolveEntities: (value: Entity[]) => void = () => {}
  vi.mocked(fetchEntities).mockReturnValue(new Promise((resolve) => { resolveEntities = resolve }))
  ```
  Assert the loading indicator, then call `resolveEntities([...])`, `await flushPromises()`, and assert the loaded state.

## 5. Example
```ts
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { fetchEntities } from '@/api/entities'
import EntityList from '@/components/entities/EntityList.vue'
import { makeEntity } from '../../../mocks/factories/entity'
import { mountWithPlugins } from '../../../utils/mount'

vi.mock('@/api/entities')

describe('EntityList', () => {
  it('shows an empty state when there are no entities', async () => {
    vi.mocked(fetchEntities).mockResolvedValue([])

    const wrapper = mountWithPlugins(EntityList)
    await flushPromises()

    expect(wrapper.get('[data-testid="entities-empty-state"]').isVisible()).toBe(true)
  })

  it('emits select with the entity id when an entity row is clicked', async () => {
    const pump = makeEntity({ id: 7, name: 'Pump' })
    vi.mocked(fetchEntities).mockResolvedValue([pump])
    const wrapper = mountWithPlugins(EntityList)
    await flushPromises()

    await wrapper.get('[data-testid="entity-row-7"]').trigger('click')

    expect(wrapper.emitted('select')).toEqual([[7]])
  })
})
```

## 6. Forbidden in component tests
- `shallowMount` by default, or stubbing every child
- Reading or setting `wrapper.vm.<anything>`, or calling component methods directly
- Selecting by Vuetify classes or DOM structure
- Snapshot-only tests, `expect(true)`, or tests without an assertion
- Real network (MSW's `onUnhandledRequest: 'error'` will fail the test)
- `setTimeout` waits or real timers in debounce tests
