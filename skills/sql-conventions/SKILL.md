---
name: sql-conventions
description: Use when writing or changing Python code that uses a database session (evermore managers, readers, creators, updaters) or declares table indexes. Enforces running every session operation in a self._session.begin_nested() transaction, keeping the try commit + handle_integrity_error block written out in each function, no session.rollback(), and indexes in __table_args__. Complements python-conventions.
---

# SQL & Transaction Conventions

Applies to code you write or change. Never to unchanged lines.

General Python style is in `python-conventions`; evermore's folder rules are in `services/evermore/CLAUDE.md`. Reviewers use `references/checklist.md`.

---

## 1. Every Session Operation Runs in a Transaction

Every operation on the session (reads, adds, updates, deletes) runs inside `with self._session.begin_nested():`. Never call the session outside one.

```python
# GOOD:
def entity_by_id(self, entity_id: int) -> Entity:
    """
    Read one entity by its id.

    :param entity_id: The id of the entity to read.
    :return: The entity.
    :raises EntityNotFoundError: When no entity has this id.
    """
    with self._session.begin_nested():
        entity: Entity | None = self._session.get(Entity, entity_id)

    if entity is None:
        raise EntityNotFoundError(f"Entity {entity_id} was not found.")

    return entity


# BAD:
def entity_by_id(self, entity_id: int) -> Entity:
    entity: Entity | None = self._session.get(Entity, entity_id)  # no transaction
    ...
```

---

## 2. The Commit Block Stays Written Out

Every write keeps its `try: self._session.commit()` + `handle_integrity_error(...)` block written out in the function itself, **even when the same block repeats in every function**. Don't extract it into a helper: reading the function top to bottom shows exactly where it commits and what happens on a conflict. `handle_integrity_error(...)` raises the right domain error; call it the way the existing functions in the same manager do.

```python
# GOOD:
def create_entity(self, entity_input: EntityInput) -> Entity:
    """
    Create an entity.

    :param entity_input: The values of the new entity.
    :return: The created entity.
    :raises EntityAlreadyExistsError: When an entity with this name exists.
    """
    entity = Entity.model_validate(entity_input)
    with self._session.begin_nested():
        self._session.add(entity)

    try:
        self._session.commit()
    except IntegrityError as error:
        handle_integrity_error(error)

    return entity


# BAD:
def create_entity(self, entity_input: EntityInput) -> Entity:
    entity = Entity.model_validate(entity_input)
    with self._session.begin_nested():
        self._session.add(entity)

    self._commit_or_raise()  # the commit block is hidden in a helper
    return entity
```

Follow the order of `begin_nested()` and the commit block that the existing functions of the same manager use.

---

## 3. No `session.rollback()`

Never call `self._session.rollback()`. The `begin_nested()` block rolls its savepoint back by itself when an error leaves it.

---

## 4. Indexes

Indexes (and constraints) are declared in the model's `__table_args__`, at the end of the class, never on the field (`Field(index=True)`).

```python
# GOOD:
class Entity(SQLModel, table=True):
    """
    A tracked item of the inventory.
    """
    __tablename__ = "entities"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)

    __table_args__ = (
        Index("ix_entities_name", "name"),
    )


# BAD:
    name: str = Field(max_length=100, index=True)
```
