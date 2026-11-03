# frontend
Full rules: the vue-conventions skill. The ones that matter most:
- SFC order: <template> (one wrapper element) → <script lang="ts"> (types only) → <script setup lang="ts"> → <style>.
- No export interface in .vue. Shared types → src/models/, shared functions → src/utils/. Prefer utils over composables.
- Props: withDefaults(defineProps<Props>(), {...}). Emits: interface Emits { 'name': [Type, Type] }, no param names.
- <script lang="ts"> holds only types (interfaces, Props/Emits, type aliases, enums). Everything else, constants
  included, goes in <script setup>: emits/props, constants, refs, computed, functions, watchers, hooks.
- Spacing: ms/me/ps/pe only, never ml/mr/pl/pr (RTL).
- Colors: Vuetify theme classes for text (text-entryText), Vuetify tokens for surfaces and borders,
  never hex/rgb. Always a theme color: never one color that stays the same when the theme changes.
  A new theme key gets a value in both light and dark. Switch the theme and check.
- Tailwind only, no d-flex/d-block. w-full/h-full, not w-[100%]. flex for sizing, rem for fonts, else vh/vw/%.
- No any; unknown + narrowing when the shape is truly unknown. === / !== only.
  Explicit checks: val !== null && val !== undefined, str.trim().length === 0, arr.length === 0.
- Every async view: loading, empty (with a message) and error states. Errors via showGlobalSnackbar, no console.log.
- API calls only under requests/.
- Every async load goes through useLoadableResource or useInfiniteListLoadableResourceWithFunction. No hand-rolled
  isLoading ref + try/catch + offset bookkeeping. No new loadable variant without asking first.
- A paged source never adds or drops rows: the page function maps every record to one row. Filtering inside it skips
  records and ends the list early (offsets advance by page.length). Filter server-side or after the page is in memory.
- The form mirrors the model: a field the service rejects when blank is required + :rules in the create/edit form.
  For every new or changed endpoint, read its create model's required fields, then the form.
- Empty areas: <template #empty> with a fixed small height inside selects and scroll lists; an empty tab or page
  carries not_found.svg.
- Naming: modal components are XModal.vue, not XDialog.vue. A component or util named for a shared concept carries
  its owner's prefix.
- A string becomes a constant only when it's used in more than one place; critical keys (storage, header, event,
  permission keys) always do. Other strings stay inline, whatever their length.
- Page sizes: what one page shows (usually 10–25).
- Frontend changes: a video of the new behaviour is suggested at the end of /feature, unless the user doesn't want it.
- No eslint-disable, @ts-ignore, @ts-expect-error. Fix the code instead.
