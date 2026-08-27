---
icon: lucide/rocket
---

# Get started

This walkthrough builds a typed repository for an application using SQLAlchemy.
It assumes the application already creates the database and runs migrations.
Read it once from top to bottom, then use the [guides](guides/index.md) by
capability.

## Install

repositron runs on Python 3.13+ and SQLAlchemy 2.0. Install the asyncio extra
for an async application; it includes SQLAlchemy's `asyncio` extra and its
`greenlet` dependency.

=== "uv"

    ```bash
    uv add "repositron[asyncio]"
    ```

=== "pip"

    ```bash
    pip install "repositron[asyncio]"
    ```

Dataclass return shapes add no further dependency. Pydantic is optional when
you already use it for API schemas.

## A model to work with

The examples use a small task tracker. It is an ordinary SQLAlchemy model; if
you already have models, use those instead.

```python
import datetime

from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(AsyncAttrs, DeclarativeBase): ...


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int]
    title: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(default="open")
    assignee_id: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=lambda: datetime.datetime.now(datetime.UTC)
    )
    archived_at: Mapped[datetime.datetime | None] = mapped_column(default=None)
```

`AsyncAttrs` is useful once a DTO or hook needs an unloaded relationship. The
[async guide](guides/async.md#relationships-and-hydration) explains when to use
it and when to prefer eager loading.

## Declare the shapes

`Repository` is generic in the model, the shape reads return, the create and
update payloads, the primary-key type, and the session type:

```python
Repository[Model, DTO = Model, Create = object, Update = object, PK = int, SessionT = Session]
```

Most applications supply the first four parameters and put `AsyncSession` in
the final slot. It makes the awaited API visible to your editor and lets `ty`
reject calls made with the wrong session mode.

```python
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from repositron import Repository, UNSET, UnsetType


@dataclass(frozen=True, slots=True)
class TaskDTO:
    id: int
    title: str
    status: str
    assignee_id: int | None


@dataclass
class TaskCreate:
    workspace_id: int
    title: str
    description: str | None | UnsetType = UNSET
    assignee_id: int | None | UnsetType = UNSET


@dataclass
class TaskUpdate:
    title: str | UnsetType = UNSET
    status: str | UnsetType = UNSET
    assignee_id: int | None | UnsetType = UNSET


class TaskRepository(
    Repository[Task, TaskDTO, TaskCreate, TaskUpdate, int, AsyncSession]
):
    pass
```

`TaskDTO` is deliberately narrower than the model: it carries what a task view
needs, not every column. `UNSET` means “leave this field alone”; `None` remains
a value, so `TaskUpdate(assignee_id=None)` writes `NULL`.

## Create a session per task

Build the engine and session factory during application startup. Create one
`AsyncSession` per request, job, or concurrent task; an `AsyncSession` is
mutable transaction state and cannot be shared between concurrent tasks.

```python
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


engine = create_async_engine("postgresql+psycopg://user:password@host/database")
sessions = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessions() as session:
        yield session


async def shutdown() -> None:
    await engine.dispose()
```

`expire_on_commit=False` keeps already-loaded attributes usable after a commit.
Always dispose an engine that leaves scope while the event loop is still alive.

## Use the repository

Inject or create the repository inside the scope that owns the session. Its
normal method names are coroutines:

```python
async def work(session: AsyncSession) -> None:
    repo = TaskRepository(session)

    task = await repo.get(1)  # TaskDTO | None
    tasks = await repo.list(workspace_id=42, status="open")  # list[TaskDTO]
    total = await repo.count(workspace_id=42)
    exists = await repo.exists(1)

    task_id = await repo.create(TaskCreate(workspace_id=42, title="Ship the docs"))
    updated = await repo.update(task_id, TaskUpdate(status="done"))
    deleted = await repo.delete(task_id)
```

Writes flush by default and leave the transaction boundary to the caller. Use
`async with sessions.begin()` when the application owns a unit of work, set
`Repository(..., autocommit=True)`, or pass `commit=True` to one write. See
[transactions](guides/updates.md#transactions) for the trade-offs.

## The synchronous counterpart

Synchronous code uses the same base with `Session` in the final generic slot
and the explicit `*_sync` methods. This is useful for a conventional worker or
script; it is not a bridge that runs async code for you.

```python
from sqlalchemy.orm import Session


class SyncTaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate, int, Session]):
    pass


def archive(session: Session, task_id: int) -> bool:
    return SyncTaskRepository(session).update_sync(task_id, TaskUpdate(status="archived"))
```

For lifecycle, relationship loading, scoped sessions, hooks, and the complete
sync mapping, continue to [Sessions and execution](guides/async.md).
