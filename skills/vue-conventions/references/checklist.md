# Vue Conventions Checklist

Applies to code you write or change. Never to unchanged lines.

Run this per changed `.vue` / `.ts` file. Every item must be answered ✅, ❌ (with `file:line`), or N/A.

In the `/feature` workflow, `scripts/check_slice.py` and `scripts/gate_a.py` run eslint and the suppression check on the changed lines only; copy their result where it covers an item. Items marked (auto) are mechanical: when no tool reported them, check them by hand. Judge only lines the branch added or changed.

## Architecture
- [ ] VU-01 Components are small and focused: genuinely reusable parts are extracted, and oversized components are split
- [ ] VU-45 `.ts` files and folders are kebab-case (`entity-status.ts`)
- [ ] VU-46 API requests live only under `requests/`; components, views, and utils call functions from there
- [ ] VU-02 No component has `v-dialog` as its root. Dialog content is its own card component, wrapped in `v-dialog` by the parent.
- [ ] VU-03 Logic, helpers, and interfaces used in more than one place are in `src/utils/` or `src/models/`
- [ ] VU-41 Utils over composables: no new composable unless more than one file uses it and a plain util in `src/utils/` can't do it
- [ ] VU-42 Files in `src/utils/` have general names (`utils/entity.ts`, not `utils/entity-names.ts`), and existing ones are reused before a new file is added
- [ ] VU-30 No condition repeats what a parent already guarantees (e.g. no `v-if="isOpen"` inside a `v-dialog` bound to `isOpen`)
- [ ] VU-32 (auto) `.vue` files export nothing (no `export` in either script block); shared types, constants, and helpers live in `src/utils/`, `src/models/`, or their own module

## SFC structure
- [ ] VU-04 Block order is `<template>` (one wrapper element), then `<script lang="ts">`, then `<script setup lang="ts">`, then `<style>` (only if needed)
- [ ] VU-05 (auto for constants and Props/Emits) Interfaces, types, enums, and all constants are in `<script lang="ts">`, and runtime logic is in `<script setup>`. No consts in `<script setup>`.
- [ ] VU-06 `<script setup>` order is emits/props, then refs, then computed, then const functions, then function declarations, then watchers, then lifecycle hooks, with single blank lines between sections
- [ ] VU-47 Refs are explicitly typed (`ref<boolean>(false)`)
- [ ] VU-48 Prop-driven logic uses `watch(..., { immediate: true })`, not a bare `onMounted`

## Props & emits
- [ ] VU-07 Emits are `interface Emits { 'name': [Type, Type] }`: tuples of types only, with no parameter names
- [ ] VU-27 (auto) Props and emits are interfaces named exactly `Props` and `Emits` (no component prefix) in `<script lang="ts">`, used as `withDefaults(defineProps<Props>(), {...})` / `defineEmits<Emits>()`. No inline type literals in the macros.
- [ ] VU-38 A component with no props or no emits doesn't call that macro

## UI
- [ ] VU-09 `EasyToolTip` is used, never raw `v-tooltip`
- [ ] VU-10 Complex titles, dialogs, and config controls have an `EasyToolTip` with `mdi-information`
- [ ] VU-11 Every async operation shows a loading state (spinner, button `:loading`, progress, skeleton)
- [ ] VU-49 Every list or async view has an empty state with a clear message
- [ ] VU-50 Independent loads are batched with `Promise.all`
- [ ] VU-12 Search and filter loading is debounced, with the delay as a named constant
- [ ] VU-13 Long, paginated or lazy lists use the infinite list / generic loadable resource (`v-infinite-scroll`)
- [ ] VU-14 User-facing errors go through `showGlobalSnackbar`, network errors through `handleNetworkError`
- [ ] VU-51 No `console.log` (or other `console.*`) in committed code
- [ ] VU-15 Important titles and primary actions are centered
- [ ] VU-39 A `data-testid` (named `<what>-<kind>`) is added only to elements a planned test uses, and none when no frontend tests are planned; inputs and buttons have accessible names (labels, button text)
- [ ] VU-31 Elements with more than one attribute have one attribute per line, with `>` / `/>`, text content, and the closing tag each on their own line

## Styling
- [ ] VU-16 (auto) No hard-coded colors (hex, literal `rgb()`/`hsl()`, named colors, Vuetify palette colors, Tailwind color classes). Colors come only from the theme in `vuetify.ts`.
- [ ] VU-52 Visual changes work in light and dark themes: text uses theme color classes (`text-entryText`), surfaces and borders use Vuetify color tokens
- [ ] VU-53 Spacing is RTL-safe: `ms-*`/`me-*`/`ps-*`/`pe-*`, never `ml-*`/`mr-*`/`pl-*`/`pr-*`
- [ ] VU-54 `w-full` / `h-full`, never `w-[100%]` / `h-[100%]`; `rem` for fonts
- [ ] VU-17 New semantic states get a new theme key (existing keys aren't reused for a different meaning)
- [ ] VU-18 No `px` for layout sizing. Uses flex, or `rem`/`vh`/`vw` when sizing is required.
- [ ] VU-19 Tailwind utilities are preferred, and scoped CSS appears only when Tailwind/Vuetify can't express the style
- [ ] VU-43 No `d-flex` or `d-block`: Tailwind's `flex` and `block`

## Clean code
- [ ] VU-20 No loose truthy/falsy checks on non-booleans, in script and in templates (`v-if`, `v-show`, ternaries): explicit `=== null`/`=== undefined`, `.length === 0`, `=== 0`
- [ ] VU-21 Empty-string checks use `.trim()` (`x.trim().length === 0`)
- [ ] VU-55 No `any`: `unknown` plus narrowing when the shape is truly unknown
- [ ] VU-56 `===` / `!==` only, never `==` / `!=`
- [ ] VU-33 (auto) No `??`, `??=`, `?.`, `!!`, or `||` / `&&` used to pick a value. Uses a full `if` with an explicit check.
- [ ] VU-34 Choosing which function to call (or whether to call one) uses a full `if` / `else`, never a ternary
- [ ] VU-44 Early returns: a loop body that is one `if` inverts it and `continue`s; a function body that is one `if` inverts it and `return`s
- [ ] VU-35 (auto) No `void` before function calls
- [ ] VU-36 Component state is a `ref`, not a reassigned `let`
- [ ] VU-37 Behavior that depends on a type or key is an object/`Record` lookup, not a chain of `if`s per type
- [ ] VU-22 (auto in scripts) No magic numbers in template or script; strings of 4+ words are named constants, and no constant holds a string of 3 words or fewer
- [ ] VU-23 Names are descriptive (no `data`, `item`, `load`)
- [ ] VU-40 (auto) No comments (`//`, `/* */`, `<!-- -->`, JSDoc) in script, template, or style
- [ ] VU-25 No trailing `return` in functions that return nothing, and no `return undefined`/`return null` to mean "nothing"
- [ ] VU-28 In `.ts` files, no export at the declaration (`export const/function/interface/type/enum/class`). One export section at the bottom of the file (`export default` only where a tool requires it).
- [ ] VU-29 URLs, links, ports, and keys come from `.env` (`VITE_*` via `import.meta.env`), never hardcoded.
