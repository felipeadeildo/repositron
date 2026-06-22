---
icon: lucide/columns-3
---

# Projection

Sometimes you have a twenty-column table and a screen that shows three of them.
Loading the whole row to throw most of it away is wasteful, and it is exactly the
sort of thing you stop noticing until a list endpoint gets slow.

??? note "Setup"

    ```python
    from __future__ import annotations

    from dataclasses import dataclass
    from datetime import datetime

    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    from repositron import Repository


    class Base(DeclarativeBase): ...


    class Task(Base):
        __tablename__ = "tasks"

        id: Mapped[int] = mapped_column(primary_key=True)
        workspace_id: Mapped[int]
        title: Mapped[str]
        description: Mapped[str | None]
        status: Mapped[str]
        assignee_id: Mapped[int | None]
        created_at: Mapped[datetime]
        archived_at: Mapped[datetime | None]


    @dataclass(frozen=True, slots=True)
    class TaskDTO:
        id: int
        title: str
        status: str
        assignee_id: int | None


    class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
        model = Task
        dto = TaskDTO


    repo = TaskRepository(session)
    ```

## Ask for a narrower shape

Index the repository with a smaller dataclass and that one call selects only the
columns that shape declares, and returns instances of it:

```python hl_lines="10"
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskCard:
    id: int
    title: str
    status: str

repo[TaskCard].list(workspace_id=42)   # SELECT id, title, status -> list[TaskCard]
repo[TaskCard].first(id=5)             # TaskCard | None
repo[TaskCard].get(5)                  # TaskCard | None
```

`get`, `first`, `list`, and `list_paginated` all project when a shape is bound.

The generated SQL is a real column projection. The database reads and ships only
`id`, `title`, and `status`, and you get back `TaskCard` objects, not full `Task`
rows you then have to trim.

## It does not disturb the repository you injected

`repo[TaskCard]` returns a lightweight clone bound to that shape for the duration
of the call. The repository you constructed and injected is untouched, so this is
safe to do anywhere, including in code that shares one repository across requests:

```python
repo.list()                  # list[TaskDTO]   (the repository's default shape)
repo[TaskCard].list()        # list[TaskCard]  (just for this call)
repo.list()                  # list[TaskDTO]   (unchanged; still the default)
```

Because the clone is cheap and stateless, reaching for a projection is never a
structural decision. It is a per-call detail.

## Field renames carry over

A projected shape can use the renamed field name; the repository's
[`field_mapping`](configuration.md#field_mapping) resolves it back to the column,
the same as for the full DTO.

```python
@dataclass(frozen=True, slots=True)
class TaskCard:
    id: int
    title: str       # field_mapping resolves this to the headline column
    status: str

repo[TaskCard].list()   # SELECT id, headline, status
```

## Where it pays off

Two patterns recur:

- **Lookups.** When you need an `id -> something` map and nothing else, project
  to just those two columns and build the dict:

    ```python
    @dataclass(frozen=True, slots=True)
    class TaskIdTitle:
        id: int
        title: str

    titles = {t.id: t.title for t in repo[TaskIdTitle].list(workspace_id=42)}
    ```

- **Fan-out.** When a background job needs each task's id and assignee and nothing
  more, projecting to that pair avoids hydrating rows you will not otherwise use.
  Here `notify` is your own job function (enqueue, push, email, whatever):

    ```python
    @dataclass(frozen=True, slots=True)
    class TaskIdAssignee:
        id: int
        assignee_id: int | None

    for task in repo[TaskIdAssignee].list(status="open"):
        if task.assignee_id is not None:
            notify(task.assignee_id)   # your job fn
    ```

Projection also composes with [pagination](pagination.md#pagination-plays-well-with-projection),
so a paginated card list fetches only the card's columns.
