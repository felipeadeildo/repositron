---
icon: lucide/shapes
---

# Return types

The DTO is the shape your reads return. repositron supports three kinds, and the
right choice is usually obvious once you know what each costs. The rule of thumb:
use a dataclass unless you have a specific reason not to.

## Dataclass: the recommendation

A dataclass DTO is light, it is detached from the session, and it serializes to
JSON without ceremony. That last point is the quiet win: the object your
repository returns is the object your web framework sends, so there is no third
hand-written schema sitting between them, drifting out of sync.

??? note "Setup"

    ```python
    from datetime import datetime

    from sqlalchemy import DateTime, Integer, String
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


    class Base(DeclarativeBase): ...


    class Task(Base):
        __tablename__ = "tasks"

        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        workspace_id: Mapped[int] = mapped_column(Integer)
        title: Mapped[str] = mapped_column(String)
        description: Mapped[str | None] = mapped_column(String)
        status: Mapped[str] = mapped_column(String)
        assignee_id: Mapped[int | None] = mapped_column(Integer)
        created_at: Mapped[datetime] = mapped_column(DateTime)
        archived_at: Mapped[datetime | None] = mapped_column(DateTime)
    ```

```python
from dataclasses import dataclass

from repositron import Repository


@dataclass(frozen=True, slots=True)
class TaskDTO:
    id: int
    title: str
    status: str
    assignee_id: int | None


class TaskRepository(Repository[Task, TaskDTO]): ...
```

In a FastAPI route, the same type is the return annotation and the response
model. `get_repo` is your dependency-injection provider, the function that builds
a `TaskRepository` bound to the request's session:

```python hl_lines="8"
from typing import Annotated

from fastapi import Depends


@app.get("/tasks")
def list_tasks(repo: Annotated[TaskRepository, Depends(get_repo)]) -> list[TaskDTO]:
    return repo.list(order_by=[Task.created_at.desc(), Task.id])
```

`frozen=True, slots=True` is a good default: immutable, low-overhead, and a clear
signal that this is a value to read, not a row to mutate.

## Model as DTO: no hydration at all

Leave the DTO parameter off and the DTO defaults to the model itself. Reads then
return the model instances directly, with no conversion step:

```python
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from repositron import Repository


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)


class WorkspaceRepository(Repository[Workspace]):   # DTO defaults to Workspace
    pass


repo.get(1)                 # Workspace | None
repo.list(name="Acme")      # list[Workspace]
```

This is the lightest path in CPU terms, since nothing is copied. The trade-off is
that what you hand back is attached to the session and is a full ORM object, so
it is best when the caller is internal and lives inside the same transaction, not
when you are about to serialize it across an HTTP boundary.

## Pydantic: reuse a schema you already have

If your project already defines a Pydantic response model, that model *is* a
valid DTO. repositron detects Pydantic and hydrates through `model_validate`, so
you do not declare the shape twice:

```python
from pydantic import BaseModel, ConfigDict

from repositron import Repository


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    status: str


class TaskRepository(Repository[Task, TaskOut]): ...

repo.list()   # list[TaskOut], ready to return over HTTP
```

The `from_attributes=True` config is what lets Pydantic read straight off the
model. Pydantic stays a genuinely optional dependency: repositron duck-types on
`model_validate` rather than importing Pydantic, so the dataclass path never pulls
it in.

## Picking, in one line each

| If you want to...                                   | Use            |
| --------------------------------------------------- | -------------- |
| return light objects over HTTP, one source of truth | dataclass      |
| work with full ORM rows inside a transaction        | model as DTO   |
| reuse an existing Pydantic response schema          | Pydantic       |

When a DTO needs a value the row alone cannot give, for instance data from
another table, add it with a [`hydrate` hook](hooks.md#enriching-the-dto). The
rarer case, a DTO the automatic build cannot produce at all, like a plain `str`,
is a [`build` hook](hooks.md#replacing-the-build) (or the equivalent `_hydrate`
override).
