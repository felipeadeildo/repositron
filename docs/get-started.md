---
icon: lucide/rocket
---

# Get started

This page builds a working, fully typed synchronous repository around a
caller-owned SQLAlchemy `Session`. It assumes your application already creates
the engine and runs migrations. Read it once, start to finish. After that, the
[guides](guides/index.md) cover each capability in depth. For `AsyncSession`,
start with [async and sync](guides/async.md).

## Install

repositron runs on Python 3.13+ and SQLAlchemy 2.0.

=== "uv"

    ```bash
    uv add repositron
    ```

=== "pip"

    ```bash
    pip install repositron
    ```

SQLAlchemy is the only runtime dependency. If your return shapes are
dataclasses, that is the whole footprint. Nothing else comes along for the ride.

## A model to work with

Everything in these docs is built around one small domain: a task tracker, with
`Task` rows that belong to a workspace. It is an ordinary SQLAlchemy model, with
nothing repositron-specific in it, so if you already have models, point
repositron at those instead.

```python
import datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase): ...


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int]
    title: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="open")     # open | in_progress | done
    assignee_id: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=lambda: datetime.datetime.now(datetime.UTC)
    )
    archived_at: Mapped[datetime.datetime | None] = mapped_column(default=None)
```

## Declare the shapes

A repository is described by type parameters. Most synchronous repositories use
the first four:

```python
Repository[Model, DTO, Create, Update]
```

`Model` is your SQLAlchemy class. `DTO` is what reads hand back. `Create` and
`Update` are the dataclasses your writes accept. We will use all four so the
example stays focused. The complete signature also has `PK` and `SessionT`:

```python
Repository[Model, DTO = Model, Create = object, Update = object, PK = int, SessionT = Session]
```

`PK` is the fifth parameter and `SessionT` is the last. Leave both at their
defaults for an integer-keyed synchronous repository. The [primary key guide](guides/primary-keys.md)
covers other keys and the [async guide](guides/async.md) shows `AsyncSession`.

```python
from dataclasses import dataclass

from repositron import UNSET, UnsetType


@dataclass(frozen=True, slots=True)
class TaskDTO:                 # the shape reads return
    id: int
    title: str
    status: str
    assignee_id: int | None


@dataclass
class TaskCreate:              # what create() accepts
    workspace_id: int
    title: str
    description: str | None | UnsetType = UNSET
    assignee_id: int | None | UnsetType = UNSET


@dataclass
class TaskUpdate:              # what update() accepts
    title: str | UnsetType = UNSET
    status: str | UnsetType = UNSET
    assignee_id: int | None | UnsetType = UNSET   # None = unassign (SET NULL)
```

`TaskDTO` is deliberately narrower than the model, it carries what a list view
needs, not every column. The `UNSET` defaults on the payloads are how a field
gets *left alone* on a write; [updating rows](guides/updates.md) covers why that
matters.

Wire the three together by subclassing `Repository`:

```python
from repositron import Repository


class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    pass
```

That is the entire class. Everything below uses this `TaskRepository`. The
[guides](guides/index.md) add the knobs, `field_mapping` for renamed columns, a
non-`int` key, hooks, as you need them.

## Use it

Hand the repository a session and every method is already there, already typed:

```python
repo = TaskRepository(session)

repo.get_sync(1)                                  # TaskDTO | None
repo.list_sync(workspace_id=42, status="open")    # list[TaskDTO]
repo.count_sync(workspace_id=42)                  # int
repo.exists_sync(1)                               # bool
repo.create_sync(TaskCreate(workspace_id=42, title="Ship the docs"))  # int (new id)
repo.update_sync(1, TaskUpdate(status="done"))    # True; title untouched
repo.delete_sync(1)                               # bool
```

Hover any of those calls in your editor. `repo.list_sync()` is `list[TaskDTO]`, not
`list[Any]`. The same object you return here is the object your web framework
serializes, so there is no second schema to keep in step.

!!! note "The session stays yours"
    repositron never opens or closes the session, and by default writes only
    `flush`, leaving when to commit and roll back to your application. When you
    do want a write committed, opt in with `Repository(session, autocommit=True)`
    or per call with `repo.create_sync(payload, commit=True)`; see
    [transactions](guides/updates.md#transactions). A repository wraps that
    session, so its lifetime and concurrency rules are the session's rules.
    Create or inject the repository within the request, job, or task that owns
    the session. This boundary is one of the [design principles](reference.md#design-principles).

## Where to go next

You now have a working repository. From here, the [Guides](guides/index.md) take
each capability one at a time, filtering, updating, pagination, projection,
return types, hooks, and the escape hatch for custom queries.
