# frontend
Full rules: the vue-conventions skill. The ones that matter most:
- SFC order: <template> (one wrapper element) → <script lang="ts"> (types only) → <script setup lang="ts"> → <style>.
- No export interface in .vue. Shared types → src/models/, shared functions → src/utils/. Prefer utils over composables.
- Props: withDefaults(defineProps<Props>(), {...}). Emits: interface Emits { 'name': [Type, Type] }, no param names.
- No consts in <script setup>.
- Spacing: ms/me/ps/pe only, never ml/mr/pl/pr (RTL).
- Colors: Vuetify theme classes for text (text-entryText), Vuetify tokens for surfaces and borders,
  never hex/rgb. Check light and dark.
- Tailwind only, no d-flex/d-block. w-full/h-full, not w-[100%]. flex for sizing, rem for fonts, else vh/vw/%.
- No any; unknown + narrowing when the shape is truly unknown. === / !== only.
  Explicit checks: val !== null && val !== undefined, str.trim().length === 0, arr.length === 0.
- Every async view: loading, empty (with a message) and error states. Errors via showGlobalSnackbar, no console.log.
- API calls only under requests/.
