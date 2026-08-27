---
icon: lucide/refresh-cw
---

# Async and sync repositories

`Repository` has one set of query rules for SQLAlchemy `Session` and
`AsyncSession` or `async_scoped_session`. The session you pass in chooses the
calling convention. The repository never creates, closes, or shares sessions
for you.

Install the asyncio extra when the application needs it:

```bash
uv add "repositron[asyncio]"
```

It installs SQLAlchemy's `asyncio` extra, which supplies `greenlet` on
platforms where SQLAlchemy requires it for its asyncio extension.

## Session lifecycle

Create the engine and session factory in application setup. Create one session
per request, job, or concurrent task, then close it in that task's scope.
`AsyncSession` is mutable transaction state and is not safe to share between
concurrent tasks.

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

Dispose an engine created in application or function scope explicitly with
`await engine.dispose()`. SQLAlchemy cannot reliably clean up async pooled
connections after the event loop has closed.

## Async endpoints

Bind a repository subclass to `AsyncSession` when it is used by an async web
application. Its normal methods are coroutines. A task-local
`async_scoped_session` is supported too.

```python
from sqlalchemy.ext.asyncio import AsyncSession

from repositron import Repository


class TaskRepository(
    Repository[Task, TaskDTO, TaskCreate, TaskUpdate, int, AsyncSession]
):
    pass


async def get_task(session: AsyncSession, task_id: int) -> TaskDTO | None:
    repo = TaskRepository(session)
    return await repo.get(task_id)
```

Use `await` for every built-in operation: `get`, `first`, `list`,
`list_paginated`, `count`, `exists`, `create`, `update`, `delete`,
`bulk_create`, `update_where`, and `delete_where`. Projection keeps its usual
shape: `await repo[TaskCard].list(order_by=Task.id)`.

## Sync workers

Pass a normal `Session` to the same base in synchronous code, such as a Celery
worker. Use the matching `_sync` method.

```python
from sqlalchemy.orm import Session


class TaskRepository(
    Repository[Task, TaskDTO, TaskCreate, TaskUpdate, int, Session]
):
    pass


def archive_task(session: Session, task_id: int) -> bool:
    repo = TaskRepository(session)
    return repo.update_sync(task_id, TaskUpdate(status="archived"))
```

The mapping is direct: `get_sync`, `first_sync`, `list_sync`,
`list_paginated_sync`, `count_sync`, `exists_sync`, `create_sync`,
`update_sync`, `delete_sync`, `bulk_create_sync`, `update_where_sync`, and
`delete_where_sync`.

## Type checking and mistakes

Keep the session type in the repository subclass. It lets `ty` reject
`repo.get_sync(...)` on an `AsyncSession` repository and `await repo.get(...)`
on a `Session` repository.

The runtime checks too. Calling the wrong mode raises `TypeError` before it
uses the database. It does not run synchronous database work in a thread, and
it does not drive a coroutine from synchronous code.

## Scoped sessions

Prefer passing `AsyncSession` directly. If an application already uses
`async_scoped_session`, bind the repository to its proxy type and remove the
scoped session when the outermost task ends. Otherwise the task and session stay
in the scoped registry. Its `scopefunc` runs whenever the proxy accesses the
underlying session, so keep it idempotent and free of side effects.

```python
from asyncio import current_task

from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session, async_sessionmaker

from repositron import Repository

factory = async_sessionmaker(engine, expire_on_commit=False)
scoped = async_scoped_session(factory, scopefunc=current_task)


class ScopedTaskRepository(
    Repository[Task, TaskDTO, TaskCreate, TaskUpdate, int, async_scoped_session[AsyncSession]]
):
    pass


async def handle_job() -> None:
    try:
        repo = ScopedTaskRepository(scoped)
        await repo.list(order_by=Task.id)
    finally:
        await scoped.remove()
```

## Hooks and custom writes

Async repository hooks may be ordinary functions or `async def` functions.
The async operation awaits an awaitable hook result. A synchronous operation
that encounters one raises `TypeError`, because it cannot safely run that
coroutine for you.

Keep synchronous hydration code away from unloaded relationships. SQLAlchemy
cannot perform lazy loading inside `_hydrate()` on an async session. Load
relationships up front with `selectinload()`, configure relationships with
`lazy="raise"`, or use an `async def` hook for extra database work. Models using
SQLAlchemy's `AsyncAttrs` can also await an unloaded relationship through
`model.awaitable_attrs.relationship_name`.

Built-in reads do not accept SQLAlchemy loader options. When a read needs
eager loading, add a custom async method and hydrate its result through the
repository:

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload


class TaskRepository(
    Repository[Task, TaskDTO, TaskCreate, TaskUpdate, int, AsyncSession]
):
    async def get_with_subtasks(self, task_id: int) -> TaskDTO | None:
        stmt = (
            select(Task)
            .where(Task.id == task_id)
            .options(selectinload(Task.subtasks))
        )
        task = (await self.session.scalars(stmt)).one_or_none()
        if task is None:
            return None
        return await self._hydrate_one_async(task)
```

`Task.subtasks` in the example is a mapped relationship. Replace it with the
relationship the DTO or hook needs. `_hydrate_one_async()` preserves the usual
build and `hydrate` hooks.

`@writes` follows the function it decorates. Decorate `async def` custom writes
for the awaited API and normal functions for the `_sync` API. In either case it
applies the same final flush, optional commit, and rollback policy as built-in
writes.

Repositron does not call `AsyncSession.run_sync()`. Keep repository calls and
hooks in the async API so every database operation remains visible as an
`await`. Reserve `run_sync()` for isolated SQLAlchemy legacy code. Its callable
runs in the event-loop thread, so ordinary blocking I/O inside it still blocks
the loop.

```python
class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate, int, AsyncSession]):
    @writes
    async def archive(self, task_id: int) -> None:
        task = await self.session.get(Task, task_id)
        if task is not None:
            task.status = "archived"
```

## Transactions and drivers

Writes still flush by default. `autocommit=True` or `commit=True` commits after
the flush. If database work fails, `rollback_on_error=True` rolls back the
caller-owned session before the error is raised.

Configure async session makers with `expire_on_commit=False` when DTO hydration
or response serialization may read attributes after a commit. Expired async ORM
attributes can otherwise trigger SQLAlchemy's `MissingGreenlet` error.

Repositron stays driver-neutral. For PostgreSQL with Psycopg 3, configure an
SQLAlchemy async engine with the Psycopg dialect in the application, then pass
the resulting `AsyncSession` to the repository.
