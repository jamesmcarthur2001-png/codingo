---
name: vue-conventions
description: Use when creating, modifying, refactoring, or reviewing Vue 3, Vuetify, TypeScript, and Tailwind frontend code. Enforces SFC block layout, constants and interfaces in <script lang="ts">, no exports from .vue files, withDefaults Props and typed Emits interfaces, script setup ordering, typed refs over let, kebab-case .ts files, utils over composables, API calls only under requests/, fully explicit conditions (no any, no ??, ?., !!, || defaults, === only), if over ternary calls, no void, no comments, no console.log, theme colors in light and dark, RTL-safe spacing, EasyToolTip, loading/empty/error states, Promise.all, showGlobalSnackbar, and styling rules.
---

# Vue 3, Vuetify & TypeScript Frontend Conventions

Applies to code you write or change. Never to unchanged lines.

Strict conventions for frontend development using Vue 3 (Composition API), Vuetify, TypeScript, and Tailwind CSS. Follow these rules whenever creating, modifying, or reviewing frontend code.

---

## 1. Component Architecture & Sizing

- **Small, Focused Components**: Prefer small, focused components over monolithic ones. Extract genuinely reusable components: when a part of a template could be used elsewhere (a field group, a toolbar, a status chip), split it into its own component. Split oversized components.
- **Dialog Decomposition (`v-dialog`)**:
  - **Never** make `v-dialog` the root element of a component.
  - Create the dialog's content as a standalone modal/card component.
  - Wrap it in `v-dialog` at the call site / parent view. This keeps the modal content independently reusable, testable, and embeddable.
- **No redundant conditions**: never repeat a condition that a parent already guarantees. For example, content inside `<v-dialog :model-value="isDialogOpen">` only shows while the dialog is open, so it must not also have `v-if="isDialogOpen"`. If the content must start fresh each time it opens (e.g. a form that initialises from its props), give it a `:key` that the parent changes every time it opens the dialog, instead of a duplicate `v-if`. A new key remounts the content even when the props didn't change, e.g. opening "Add" twice in a row.
- **Shared Code Extraction**:
  - Any logic, helper functions, or TypeScript interfaces used in more than one place **must** be extracted into `src/utils/` or `src/models/`.
  - **Utils over composables**: we rarely use composables; shared logic goes in `src/utils/`. Never create a composable unless more than one file needs it and a plain util can't do it. Logic one component uses stays in that component.
  - **General names in `src/utils/`**: name a utils file after the general subject and reuse existing ones before adding a file: `utils/entity.ts`, not `utils/entity-names.ts`.
- **Kebab-case `.ts` files and folders**: `utils/entity-status.ts`, `requests/asset-types/`, never `entityStatus.ts` or `entity_status.ts`.
- **API requests only under `requests/`**: components, views, and utils never call the HTTP client directly; they call a function from `requests/`.
- **No exports from `.vue` files**: a `.vue` file never exports anything (no `export`, `export type`, or `export { ... }` in either script block). Anything another file needs (a type, a constant, a helper) belongs in `src/utils/`, `src/models/`, or the module it's really about, and both the component and the other file import it from there.

---

## 2. Single File Component (SFC) Structure

Every Vue SFC must follow this exact top-to-bottom block order:

1. `<template>`, with a single wrapper element under it
2. `<script lang="ts">`, then `<script setup lang="ts">`
3. `<style>` (only if necessary)

No `export interface` (or any export) in a `.vue` file: shared types go to `src/models/`, shared functions to `src/utils/` (§1).

### Script Tag Splitting

Separate static type declarations from reactive runtime logic using two `<script>` tags:

1. `<script lang="ts">`: Contains component-specific interfaces (including the component's `Props` and `Emits` interfaces), types, enums, and **all** constants (timeouts, debounce delays, magic numbers, long strings). Constants never go in `<script setup>`. Nothing in it is exported (see §1).
2. `<script setup lang="ts">`: Contains component runtime logic and reactive state. **No consts in `<script setup>`**: constant values (numbers, strings, lists, maps) go in `<script lang="ts">`. The only `const`s there are the sections of §3 (`emit`, `props`, refs, computeds, const functions).

```vue
<template>
  <div class="flex flex-col gap-4">
    <span>{{ user.name }}</span>
  </div>
</template>

<script lang="ts">
interface UserCardItem {
  id: string
  name: string
  role: string
}

interface Props {
  user: UserCardItem
  initialStatus?: boolean
}

interface Emits {
  'update': [string, boolean]
  'close': []
}

const DEFAULT_AVATAR_FALLBACK = '/assets/default-avatar.png'
const DEBOUNCE_DELAY_MS = 300
</script>

<script setup lang="ts">
const emit = defineEmits<Emits>()

const props = withDefaults(defineProps<Props>(), {
  initialStatus: false,
})
</script>

<style scoped>
.user-card-avatar {
  aspect-ratio: 1;
}
</style>
```

---

## 3. Strict `<script setup>` Internal Ordering

The contents of `<script setup lang="ts">` must follow this exact sequence, with single empty lines separating each section:

1. **`defineEmits` & `defineProps`**:
2. **`ref`s / reactive state**:
3. **`computed` properties**:
4. **Const functions**: `const fn = () => {}`.
5. **Function declarations**: `function fn() {}`.
6. **Watchers (`watch`, `watchEffect`)**:
7. **Lifecycle hooks (`onBeforeMount`, `onMounted`, `onUnmounted`, ...)**:

Constants are not a section here: they live in `<script lang="ts">` (§2).

Every item sits in its own section: never declare a ref after a function, or a computed after a watcher.

### Example `<script setup>` Layout

```vue
<script setup lang="ts">
const emit = defineEmits<Emits>()

const props = withDefaults(defineProps<Props>(), {
  initialStatus: false,
})

const isActionLoading = ref<boolean>(false)
const searchFilter = ref<string>('')

const hasActiveFilter = computed<boolean>(() => searchFilter.value.trim().length > 0)

const executeUserUpdate = async () => {
  isActionLoading.value = true
  try {
    await saveUserSelection(props.user.id)
    emit('update', props.user.id, true)
  } catch (error: unknown) {
    handleNetworkError(error)
  } finally {
    isActionLoading.value = false
  }
}

function clearSearchFilter() {
  searchFilter.value = ''
}

watch(searchFilter, () => {
  debouncedSearch()
})

watch(() => props.user.id, () => {
  loadUserPermissions()
}, { immediate: true })

onMounted(() => {
  focusSearchField()
})
</script>
```

- **Refs are explicitly typed**: `ref<boolean>(false)`, `ref<Entity[]>([])`, `ref<number | null>(null)`.
- **Prop-driven logic uses `watch(..., { immediate: true })`**, not a bare `onMounted`: it runs on mount and again whenever the prop changes.

---

## 4. Props & Emits Rules

- **Always use interfaces named `Props` and `Emits`**: declare them in the `<script lang="ts">` block, not exported, and pass them: `defineProps<Props>()`, `defineEmits<Emits>()`. The file already says which component they belong to, so never prefix them (no `UserCardProps`, `ActiveEntitySelectEmits`).
  - **Never** write the type inline inside the macro: no `defineProps<{ ... }>()` and no `defineEmits<{ ... }>()`.
  - A component with no props or no emits doesn't call that macro at all.
- **Props via `withDefaults`**: `const props = withDefaults(defineProps<Props>(), { ... })`, with a default for every optional prop.
- **Emits format**: `interface Emits { 'name': [Type, Type] }`, one quoted event name per line, mapped to a tuple of types.
- **`defineEmits` Parameter Naming**:
  - In `defineEmits`, do **NOT** name tuple parameters; specify types only.
  - BAD: `'update': [userId: string, isSelected: boolean]`
  - GOOD: `'update': [string, boolean]`

---

## 5. UI Elements & Layout Patterns

### Template Formatting

When an element or component has **more than one attribute** (props, directives, events, `data-testid`, ...), put each part on its own line: the opening tag name, each attribute, the closing `>`, the text content, and the closing tag. An element with at most one attribute may stay on one line when it's short.

```vue
<!-- GOOD: -->
<v-btn
  variant="text"
  data-testid="retry-asset-types-button"
  @click="loadPage"
>
  Retry
</v-btn>

<!-- BAD: -->
<v-btn variant="text" data-testid="retry-asset-types-button" @click="loadPage">Retry</v-btn>
```

The same applies to self-closing components: each attribute on its own line, and `/>` on its own line.

### Tooltips (`EasyToolTip`)

- **Always use `EasyToolTip`**: Never use raw `v-tooltip`.
- **Complex UI Headers & Dialogs**: Whenever presenting complex titles, modals, dialogs, or intricate configuration controls, include an `EasyToolTip` featuring an `mdi-information` icon to provide hover explanation context to the user.

### Loading States & Async Handling

- **Visual Loading Indicators**: Always indicate loading state during asynchronous operations (a spinner, or `:loading="isActionLoading"` on buttons, progress bars, or skeletons). Never leave users without visual feedback during network operations.
- **Empty state**: every list or async view has an empty state with a clear message (`No assets yet.`), not a blank area.
- **Independent loads together**: loads that don't depend on each other run in one `await Promise.all([...])`, not one `await` after another.
- **Debounced Loading**: Always debounce search and filter-driven loading functions. All debounce timeout values must be declared as named constants (e.g. `const SEARCH_DEBOUNCE_MS = 300`).
- **Long lists**: use the infinite list / generic loadable resources (built on `v-infinite-scroll`) for paginated lists, feeds, and lazy-loaded datasets.
- **Error Handling**: user-facing errors are shown through `showGlobalSnackbar`; network/API errors go through `handleNetworkError`. Never `console.log` (or any `console.*`) in committed code.

### Alignment & Typography

- **Centering**: Center important titles and primary action buttons.

---

## 6. Styling, Themes & CSS

- **Light and dark themes**: every visual change renders correctly in both. Text uses Vuetify theme color classes (`text-entryText` recommended); surfaces and borders use Vuetify color tokens. Never hex or `rgb()`.
- **Colors come only from the theme** defined in the project's `vuetify.ts`: theme names (`color="primary"`, `text-primary`, `bg-surface`) or `rgb(var(--v-theme-primary))` in CSS. Never hard-code a color anywhere (template, script, or style): no hex (`#ff0000`), no `rgb()` / `hsl()` with literal values, no named colors (`red`, `white`), no Vuetify palette colors (`color="red"`, `bg-red-lighten-1`), and no Tailwind color classes (`text-red-500`, `bg-white`). When no theme color fits, add a new key to the theme in `vuetify.ts`.
- **Semantic Theme Keys**:
  - Never reuse existing theme colors for differing semantic intentions.
  - If a new semantic UI state is introduced, define a new semantic theme key in the theme configuration, even if its initial hex color value matches an existing theme key.
- **No Pixel (`px`) Sizing for Layouts**:
  - Never use `px` for layout dimensions or container sizing.
  - Use flexbox (`flex`, `flex-1`, `flex-grow`, `justify-between`, `gap-*`).
  - If explicit sizing is strictly necessary, use relative viewport or font units: `vh`, `rem`, `vw`.
- **Tailwind CSS First**:
  - Prefer Tailwind CSS utility classes over scoped CSS.
  - Never use `d-flex` or `d-block` (not native Tailwind): use Tailwind's `flex` and `block`.
  - `w-full` / `h-full`, never `w-[100%]` / `h-[100%]`.
  - `flex` / `flex-grow` for component sizing, `rem` for fonts, otherwise `vh` / `vw` / `%`.
- **RTL-safe spacing**: margins and paddings use the logical classes `ms-*`, `me-*`, `ps-*`, `pe-*`, never `ml-*`, `mr-*`, `pl-*`, `pr-*`, so the layout works in RTL and LTR.
  - Use scoped `<style>` only for reusable custom component classes or CSS that cannot be expressed via Tailwind / Vuetify utilities.

---

## 7. General Clean Code Standards

- **Full & Explicit Checks (No Loose Falsy Checks)**:
  - Every condition says exactly what it checks, in script **and** in templates (`v-if`, `v-else-if`, `v-show`, `:disabled`, ternaries). `v-if="user"` and `v-if="!items.length"` are loose checks: write `v-if="user !== null"` and `v-if="items.length === 0"`.
  - Always perform full, explicit condition checks instead of loose truthy/falsy checks.
  - **Never** write `if (!test)` or `if (test)` on objects, strings, numbers, arrays, or nullable/optional variables.
  - Fully check what you actually want to evaluate:
    - Null / Undefined: `if (test === null || test === undefined)`
    - Empty string: **always with `.trim()`**: `if (test.trim().length === 0)`. Never raw `=== ''`, which misses whitespace-only strings.
    - Empty array / collection: `if (test.length === 0)`
    - Numeric check: `if (test === 0)`
  - **Boolean Exception**: Only when a variable is strictly of type `boolean` (`true` or `false`), you may use `if (test)` or `if (!test)`.
- **No `any`**: when the shape is truly unknown, use `unknown` and narrow it. eslint may not catch every `any`; check by hand.
- **`===` / `!==` only**, never `==` / `!=`.
- **No shortcut operators**: never use `??`, `??=`, `?.`, `!!`, or `||` / `&&` to pick a value (`user.name || 'Unknown'`, `items || []`). Write a full `if` with the explicit `=== null` / `=== undefined` / `.length === 0` check, so the reader sees exactly which values are handled. `&&` and `||` between booleans in a condition are fine (`if (isOpen && isReady)`).
- **Early returns**: when the rest of a block depends on a condition, check the opposite condition and leave early. A loop whose body is one `if` inverts it and `continue`s; a function whose body is one `if` inverts it and `return`s.
  ```ts
  for (const asset of assets) {
    if (asset.status !== AssetStatus.Active) {
      continue
    }

    scheduleInspection(asset)
  }
  ```
- **`if` over ternary for calls**: when the choice is which function to call (or whether to call one), use a full `if` / `else`, never a ternary (`isEditing ? updateAsset() : createAsset()`).
- **No `void` before calls**: call the function as it is (`loadPage()`), or `await` it when the order matters. Never write `void loadPage()`.
- **Prefer `ref` over `let`**: component state in `<script setup>` is a `ref` (`const selectedSiteId = ref<number | null>(null)`), not a reassigned `let`. A `let` isn't reactive, so the template and watchers never see its changes.
- **Extract Constants**: Never leave magic numbers scattered in template or script bodies; extract them into named constants in `<script lang="ts">`.
- **Strings**: strings of **4+ words** (messages, long URL paths, multi-line text) become named constants. Strings of **3 words or fewer** (labels, keys, `'Save asset'`) stay inline where they're used: moving them into constants only hides them and makes quick text changes slower. A constant that holds a string of 3 words or fewer is a violation.
- **Mappings over long if chains**: behavior that depends on a type or key is a lookup in an object or `Record` (type → value, handler, or component), not one `if` per type. Adding a type then means adding one entry.
- **Configuration in `.env`**: API base URLs, links to other systems, ports, keys, and every other environment-specific value live in the app's `.env` files (`VITE_*`) and are read through `import.meta.env` in one config module. Never hardcode them.
- **Exports at the bottom**: in `.ts` files, never export at the declaration (`export const`, `export function`, `export interface`, `export type`, `export enum`, `export class`). Declare everything first, then end the file with one export section (`.vue` files export nothing, see §1):
  ```ts
  const fetchEntities = async (): Promise<Entity[]> => { /* ... */ }
  interface Entity { id: number; name: string }

  export type { Entity }
  export { fetchEntities }
  ```
  The only exception is `export default`, where a tool requires it (e.g. `vite.config.ts`, `vitest.config.ts`, `playwright.config.ts`); keep it as the file's last statement.
- **Indicative Variable Naming**: Use clear, descriptive variable and function names (e.g., `isUserDeletionPending`, `loadUserProfileDetails`), never generic names like `data`, `item`, or `load`.
- **No comments**: no `//`, `/* */`, `<!-- -->`, and no JSDoc blocks, in script, template, or style. Clean, typed, well-named code is self-documenting.
- **No Trailing `return`**: Functions that return nothing must not end with a bare `return`. Use `return` only for an early exit. Never write `return undefined` or `return null` to mean "nothing".

---

## 8. Testing

Frontend tests follow the **`vitest-conventions`** skill (component tests with Vue Test Utils, integration tests with MSW) and the **`browser-test-conventions`** skill (Playwright with a mocked backend). Frontend tests cover **only core behavior**: shared code (used by more than one component) and important flows. There's no frontend coverage target (see `vitest-conventions`, "What Gets a Frontend Test"). Add a stable `data-testid` (`<what>-<kind>`, e.g. `save-entity-button`) only to elements a planned test queries or asserts. When the test plan has no frontend tests, add none. Inputs and buttons always have accessible names (labels on inputs, text on buttons). Reviewers use `references/checklist.md`.
