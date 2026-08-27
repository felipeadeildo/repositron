<h1 align="center">repositron</h1>

<p align="center">
    <em>A typed, generic repository base for SQLAlchemy 2.0. Full CRUD, zero per-table boilerplate.</em>
</p>

<p align="center">
<a href="https://github.com/felipeadeildo/repositron/actions/workflows/test.yml">
    <img src="https://github.com/felipeadeildo/repositron/actions/workflows/test.yml/badge.svg" alt="Test">
</a>
<a href="https://github.com/felipeadeildo/repositron/actions/workflows/release.yml">
    <img src="https://github.com/felipeadeildo/repositron/actions/workflows/release.yml/badge.svg" alt="Release">
</a>
<a href="https://pypi.org/project/repositron">
    <img src="https://img.shields.io/pypi/v/repositron?color=%2334D058&label=pypi" alt="Package version">
</a>
<a href="https://pypi.org/project/repositron">
    <img src="https://img.shields.io/pypi/pyversions/repositron.svg?color=%2334D058" alt="Supported Python versions">
</a>
<a href="https://github.com/felipeadeildo/repositron/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
</a>
</p>

<p align="center">
    <strong><a href="https://repositron.fa.dev.br">Documentation</a></strong>
    &middot;
    <a href="https://repositron.fa.dev.br/guides/filtering/"><strong>Filtering</strong></a>
    &middot;
    <a href="https://repositron.fa.dev.br/guides/projection/"><strong>Projection</strong></a>
    &middot;
    <a href="https://repositron.fa.dev.br/guides/hooks/"><strong>Hooks</strong></a>
    &middot;
    <a href="https://repositron.fa.dev.br/guides/async/"><strong>Sessions</strong></a>
    &middot;
    <a href="https://repositron.fa.dev.br/reference/"><strong>API</strong></a>
</p>

---

Every SQLAlchemy project rewrites the same repository layer: a class per table
wrapping `select(...)` / `session.scalars(...)`, the same `get` / `list` /
`count`, the same pagination math, the same "turn the ORM row into something
light to return". It is mechanical, easy to get subtly wrong, and you write it
again for the next table.

repositron writes that layer once, generically. Declare a model (and optionally a
DTO and write payloads), inherit one class, and get a fully typed repository,
every method checked against the types you declared.

```python
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from repositron import Repository, UNSET, UnsetType


@dataclass(frozen=True, slots=True)
class TaskDTO:                 # light, detached, serializes straight to JSON
    id: int
    title: str
    status: str
    assignee_id: int | None


@dataclass
class TaskCreate:
    workspace_id: int
    title: str


@dataclass
class TaskUpdate:
    title: str | UnsetType = UNSET            # absent = leave alone
    status: str | UnsetType = UNSET
    assignee_id: int | None | UnsetType = UNSET   # None = unassign (SET NULL)


class TaskRepository(
    Repository[Task, TaskDTO, TaskCreate, TaskUpdate, int, AsyncSession]
):
    pass                                       # the whole repository
```

That is the whole repository. `get` / `first` / `list` / `list_paginated` /
`count` / `exists` / `create` / `update` / `delete` all come for free, typed
against `TaskDTO`:

```python
async def use_tasks(session: AsyncSession) -> None:
    repo = TaskRepository(session)

    task = await repo.get(1)  # TaskDTO | None
    tasks = await repo.list(workspace_id=42, status="open", order_by=Task.created_at.desc())
    page = await repo.list_paginated(0, 20, order_by=Task.created_at.desc())
    task_id = await repo.create(TaskCreate(workspace_id=42, title="Ship the docs"))
    updated = await repo.update(task_id, TaskUpdate(status="done"))
```

This is the default path for FastAPI and any asyncio application. The
[async guide](https://repositron.fa.dev.br/guides/async/) covers session
lifetime, relationship loading, hooks, and custom writes. For a conventional
script or worker, bind the same base to `Session` and call `get_sync`,
`list_sync`, and the other explicit sync methods.

## Why repositron

**It cuts the layer you keep rewriting.** One generic base replaces the
per-table CRUD class, and every method is typed off the generic parameters, so
your editor knows `await repo.list()` returns `list[TaskDTO]` and `repo.get(id)`
is checked against the key type you declared (`int`, `str`, `uuid.UUID`).

**Two ways to filter, in one call.** Equality is keyed by attribute name,
anything else is a plain SQLAlchemy expression, and they combine. A `None` value
means `IS NULL`; `UNSET` skips the filter, so optional query params pass straight
through without branching.

```python
await repo.list(workspace_id=42, extra_filters=[Task.archived_at.is_(None)], order_by=Task.id)
# WHERE workspace_id = 42 AND archived_at IS NULL ORDER BY id  (open, non-archived)
```

**Updates that can actually write `NULL`.** `UNSET` means "leave this column
alone", `None` means "set it to NULL", the distinction the hand-written
`if x is not None` pattern silently loses. `TaskUpdate(assignee_id=None)`
unassigns a task; `TaskUpdate(status="done")` leaves the assignee untouched.

**Projection that is real column selection.** Index the repo with a narrow shape
and it narrows the `SELECT` itself, it does not fetch the row and drop fields. The
injected repository is untouched, the projection lasts only for the call.

```python
@dataclass(frozen=True, slots=True)
class TaskCard:
    id: int
    title: str
    status: str

await repo[TaskCard].list(workspace_id=42, status="open")
# SELECT tasks.id, tasks.title, tasks.status FROM tasks
#   WHERE workspace_id = 42 AND status = 'open'
#   -> list[TaskCard]   (only those three columns ever leave the database)
```

**Extend without overriding.** [Hooks](https://repositron.fa.dev.br/guides/hooks/)
layer a derived column, an enriched DTO, or an audit row onto the base, and
[`@writes`](https://repositron.fa.dev.br/guides/custom-queries/#writes) gives a
custom write the same flush/commit/rollback the built-ins get, no `self.session`
plumbing.

**Your choice of DTO.** A dataclass that serializes straight to JSON (so the same
object is your repository return value and your FastAPI `response_model`), the
model itself, or a Pydantic schema you already have.

## Install

```bash
uv add "repositron[asyncio]"        # or: pip install "repositron[asyncio]"
```

Requires Python 3.13+ and `sqlalchemy>=2.0`. The asyncio extra installs
SQLAlchemy's async support; Pydantic remains optional.

## Documentation

Full guides and API reference at **[repositron.fa.dev.br](https://repositron.fa.dev.br)**.

## License

MIT. See [LICENSE](LICENSE).
