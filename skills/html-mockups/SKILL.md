---
name: html-mockups
description: Use in the /feature grill when the user wants an HTML preview of new views, dialogs or layout changes before the spec. Writes static, offline mockups (plain HTML/CSS, no CDN, light/dark and RTL toggles, empty/loading/error states) close to Vuetify's look, in docs/features/<ticket>/mockups/.
---

# HTML mockups

Static previews the user opens in a browser before the spec is written. They show layout and states, not real behaviour. The setup is air-gapped, so a mockup loads **nothing** from the network.

## Rules
- One file per screen or dialog: `docs/features/<ticket>/mockups/<screen>.html` (kebab-case, e.g. `entity-export-dialog.html`). Start from `templates/mockup.html`.
- Plain HTML and CSS in the one file. No CDN, no web fonts, no images from the network, no frameworks, no JavaScript. The toggles in the template work with CSS only.
- Light/dark: keep the template's theme switch; colors come only from its CSS variables (`--surface`, `--on-surface`, `--primary`, …), never written inline.
- RTL-safe: only logical properties (`margin-inline-start`, `padding-inline-end`, `inset-inline-start`, `text-align: start`). Never `left`/`right`, `margin-left`, `padding-right`. Check it with the template's RTL switch.
- Close to Vuetify: the template's cards, buttons, text fields, data table, chips and snackbar. Use the real labels and column names from the spec draft and `grill-notes.md`, and realistic sample rows.
- Every async view shows its **content, empty (with a message), loading and error** states; the template's state switch picks one.
- Mark anything still open with a dashed `.open-question` box naming the unknown.

## Workflow
1. List the screens the feature adds or changes (from `context.md` and the grill so far).
2. Write one mockup per screen.
3. Tell the user the paths (absolute) and ask, in the next grill round, what to change. Quote their words when they refer to a requirement.
4. Apply the changes; repeat until they approve. Record `Mockups approved: <file list>` in `grill-notes.md`.
5. The spec links each approved mockup from the requirement it shows.
