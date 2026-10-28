| Test name | What it checks | Expected result | File |
|---|---|---|---|
| `test_entity_by_id_missing_id_raises_entity_not_found_error` | Reading an entity id that doesn't exist | Raises `EntityNotFoundError` with "Entity 7 was not found." | `tests/entities/test_read_entity.py` |
| `emits select with the entity id when an entity row is clicked` | Clicking a row in the entity list | `select` emitted once with `7` | `tests/unit/components/entities/EntityList.spec.ts` |
| `user creates an entity and sees it in the list` | The full create journey in Chromium, mocked API | A row with "Pump" is visible | `tests/e2e/entities/create-entity.spec.ts` |
