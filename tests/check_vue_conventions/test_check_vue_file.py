from pathlib import Path

import pytest

from check_vue_conventions import check_vue_file

COMPLIANT_COMPONENT = """<template>
  <div class="flex flex-col w-full text-entryText bg-surface">
    <v-select :items="items">
      <template #empty>
        <span class="text-entryText">{{ SHARED_MESSAGE }}</span>
      </template>
    </v-select>
    <span>{{ SHARED_MESSAGE }}</span>
  </div>
</template>

<script lang="ts">
interface Props {
  name: string
}

type Mode = 'list' | 'grid'
</script>

<script setup lang="ts">
const props = defineProps<Props>()

const SHARED_MESSAGE = 'Nothing to show here yet, add one'
const STORAGE_KEY = 'entities-view'

const isLoading = ref<boolean>(false)

function countRows() {
  let total = 0
  return total
}
</script>

<style scoped>
.title {
  font-size: 1rem;
  color: rgb(var(--v-theme-primary));
}
</style>
"""


def write_component(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "EntityList.vue"
    path.write_text(text, encoding="utf-8")
    return path


def rule_ids(path: Path) -> list[str]:
    return [violation.rule_id for violation in check_vue_file(path)]


def test_check_vue_file_compliant_component_has_no_violations(tmp_path: Path):
    path = write_component(tmp_path, COMPLIANT_COMPONENT)

    violations = check_vue_file(path)

    assert violations == []


@pytest.mark.parametrize("old,new,expected_rule_id", [
    ("type Mode = 'list' | 'grid'", "const PAGE_SIZE = 20", "VU-05"),
    ("const STORAGE_KEY = 'entities-view'", "const SAVE_LABEL = 'Save the entity now'", "VU-22"),
    ("const SHARED_MESSAGE = 'Nothing to show here yet, add one'", "const SHARED_MESSAGE = 'Nothing yet'", "VU-22"),
    ("const isLoading = ref<boolean>(false)", "let isLoading = false", "VU-36"),
    ("text-entryText bg-surface", "text-gray-500", "VU-16"),
    ("<v-select :items=\"items\">", "<v-select color=\"red\" :items=\"items\">", "VU-16"),
    ("<span>{{ SHARED_MESSAGE }}</span>", "<span :style=\"{ color: '#ff0000' }\">{{ SHARED_MESSAGE }}</span>", "VU-16"),
    ("color: rgb(var(--v-theme-primary));", "color: rgb(12, 34, 56);", "VU-16"),
    ("w-full", "w-[100%]", "VU-54"),
    ("font-size: 1rem;", "font-size: 14px;", "VU-54"),
    ("flex flex-col", "flex flex-col h-[24px]", "VU-18"),
    ("flex flex-col", "d-flex flex-col", "VU-43"),
])
def test_check_vue_file_reports_the_broken_rule(tmp_path: Path, old: str, new: str, expected_rule_id: str):
    path = write_component(tmp_path, COMPLIANT_COMPONENT.replace(old, new))

    reported_rule_ids = rule_ids(path)

    assert expected_rule_id in reported_rule_ids


def test_check_vue_file_slot_shorthand_is_not_a_hex_color(tmp_path: Path):
    path = write_component(tmp_path, COMPLIANT_COMPONENT.replace("<template #empty>", "<template #add>"))

    reported_rule_ids = rule_ids(path)

    assert "VU-16" not in reported_rule_ids
