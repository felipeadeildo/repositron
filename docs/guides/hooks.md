---
icon: lucide/webhook
---

# Hooks

Most repositories need to do a little something *around* a write or a read: set a
timestamp, derive a column from the others, fill a DTO field that no single
column backs, write an audit row. The instinct is to override `create` or
`_hydrate` and do it there, but then you inherit the parts you did not want to
touch, the `add` / `flush` / return-the-id work on a write, every other field on
a DTO.

Hooks are how you do this without overriding anything. You tag a method with
`@on`, say *when* it runs, and the repository calls it at that point inside its
own `create` / `update` / `delete` / [hydration](../concepts.md#hydration). You
write only the part that is yours; repositron keeps doing the rest. This is the
normal way to extend a repository, an override is the rare fallback at the end of
this page.

??? note "Setup"
    The examples on this page share one task-tracker domain. `Task` is the
    aggregate, `AuditEntry` records writes, and `Comment` hangs off a task for the
    counters further down.

    ```python
    from dataclasses import dataclass
    from datetime import datetime

    from sqlalchemy import ForeignKey
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


    class Base(DeclarativeBase): ...


    class Task(Base):
        __tablename__ = "tasks"

        id: Mapped[int] = mapped_column(primary_key=True)
        workspace_id: Mapped[int]
        parent_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
        title: Mapped[str]
        description: Mapped[str | None]
        status: Mapped[str]
        assignee_id: Mapped[int | None]
        created_at: Mapped[datetime]
        updated_at: Mapped[datetime | None]
        archived_at: Mapped[datetime | None]


    class AuditEntry(Base):
        __tablename__ = "audit_entries"

        id: Mapped[int] = mapped_column(primary_key=True)
        task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
        action: Mapped[str]
        at: Mapped[datetime]


    class Comment(Base):
        __tablename__ = "comments"

        id: Mapped[int] = mapped_column(primary_key=True)
        task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))


    @dataclass(frozen=True)
    class TaskDTO:
        id: int
        title: str
        status: str
        assignee_id: int | None


    @dataclass(frozen=True)
    class TaskCreate:
        workspace_id: int
        title: str
        description: str | None = None
        assignee_id: int | None = None


    @dataclass(frozen=True)
    class TaskUpdate:
        title: str | None = None
        description: str | None = None
        status: str | None = None
        assignee_id: int | None = None
    ```

```python hl_lines="6 8-9"
from datetime import UTC, datetime
from repositron import Repository, on


class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    @on("create", mode="before")
    def set_defaults(self, model: Task, payload: TaskCreate) -> None:
        model.created_at = datetime.now(UTC)
        model.status = "open"
```

That is the whole repository. `create` still builds the model from the payload,
flushes, returns the new id, and commits if asked. Right before the flush, your
hook runs and sets `created_at` and the default `status`. No `create` override,
no `self.session`, no plumbing.

## How it works

`@on` does not call your method, it tags it, hanging a small `(event, mode)`
marker on the function. When the class is defined, the base scans itself once,
through [`__init_subclass__`](https://docs.python.org/3/reference/datamodel.html#object.__init_subclass__),
collects every tagged method, and records which moment each belongs to. From
then on, `create`, `update`, `delete`, and hydration call into that collection at
the right point.

Collecting at class-definition time means no per-call cost and nothing magic at
runtime. It also means a typo fails loudly: `@on("craete", ...)` raises a
`TypeError` the moment the module is imported, rather than quietly never running.

## The events

A hook attaches to an `event` and a `mode`. Each pair passes a fixed set of
arguments, the model and, where it applies, the payload or the built DTO.

| `@on(...)`           | runs                                       | receives         | returns |
| -------------------- | ------------------------------------------ | ---------------- | ------- |
| `"create", "before"` | after the model is built, before flush     | `model, payload` | nothing |
| `"create", "after"`  | after flush, the model now has its key     | `model`          | nothing |
| `"update", "before"` | after the payload is applied, before flush | `model, payload` | nothing |
| `"update", "after"`  | after flush                                | `model`          | nothing |
| `"delete", "before"` | before the row is deleted                  | `model`          | nothing |
| `"delete", "after"`  | after flush                                | `model`          | nothing |
| `"hydrate", "build"` | to construct the DTO, on every read        | `model`          | the DTO |
| `"hydrate", "after"` | after the DTO is built, on every read      | `model, dto`     | the DTO |

`before` runs while the row is still being shaped, the place to set a column or
derive a default. `after` runs once the flush has assigned the primary key, which
is when you can write related rows that point back to it:

```python
class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    @on("create", mode="after")
    def log_creation(self, model: Task) -> None:
        # model.id exists now, so the audit row can reference it
        self.session.add(
            AuditEntry(task_id=model.id, action="created", at=datetime.now(UTC))
        )
```

That `after` hook shares the repository's transaction, so the audit row flushes
and commits together with the task. (When you want a write to *not* commit yet,
see [transactions](updates.md#transactions).)

`before` hooks mutate the model in place; nothing is returned. A common use is
normalizing input regardless of how the caller spelled it:

```python
class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    @on("create", mode="before")
    @on("update", mode="before")
    def normalize_title(self, model: Task, payload) -> None:
        if model.title:
            model.title = model.title.strip()
```

## Enriching the DTO

`hydrate` is the read-side event, and it replaces the most common reason to
override `_hydrate`: a [DTO](../concepts.md#dto) with a field that no single
column backs, a count, an aggregate, a list gathered from a related table.

A `hydrate` hook receives the DTO repositron already built, every column field
filled in and correctly typed, and returns one. With a frozen dataclass,
[`dataclasses.replace`](https://docs.python.org/3/library/dataclasses.html#dataclasses.replace)
adds the one field you care about and leaves the rest untouched:

```python
from dataclasses import dataclass, replace
from sqlalchemy import func, select
from repositron import Repository, on


@dataclass(frozen=True)
class TaskDetail:
    id: int
    title: str
    status: str
    assignee_id: int | None
    comment_count: int = 0
    subtask_count: int = 0


class TaskRepository(Repository[Task, TaskDetail]):
    @on("hydrate", mode="after")
    def add_comment_count(self, model: Task, dto: TaskDetail) -> TaskDetail:
        count = self.session.scalar(
            select(func.count()).where(Comment.task_id == model.id)
        )
        return replace(dto, comment_count=count or 0)
```

Overriding `_hydrate` for this would mean restating every field of `TaskDetail`
just to add `comment_count`. The hook adds the derived field and nothing else,
the base's typed construction does the rest. It runs on every read that
hydrates, `get`, `first`, `list`, `list_paginated`, so the field is always
present.

Hooks chain, so several `hydrate` hooks each enrich the DTO in turn:

```python
class TaskRepository(Repository[Task, TaskDetail]):
    @on("hydrate", mode="after")
    def add_comment_count(self, model: Task, dto: TaskDetail) -> TaskDetail:
        return replace(dto, comment_count=self._count_comments(model.id))

    @on("hydrate", mode="after")
    def add_subtask_count(self, model: Task, dto: TaskDetail) -> TaskDetail:
        return replace(dto, subtask_count=self._count_subtasks(model.id))

    def _count_comments(self, task_id: int) -> int:
        return self.session.scalar(
            select(func.count()).where(Comment.task_id == task_id)
        ) or 0

    def _count_subtasks(self, task_id: int) -> int:
        return self.session.scalar(
            select(func.count()).where(Task.parent_id == task_id)
        ) or 0
```

!!! note "Projection skips hydrate hooks"
    `repo[Shape]` reads only the columns `Shape` declares and builds it directly
    (see [projecting columns](projection.md)), it never hydrates a full model. A
    `hydrate` hook therefore does not fire for a projected shape, which is what
    you want: a narrow shape has nowhere to put the derived field.

## Replacing the build

`build` is the read-side event for the other case: a DTO the automatic build
*cannot produce at all*. Not a field short, like the `after` hook above, but a
shape the base has no way to construct, the classic one being a plain `str`.

The base already registers its own `build` hook, the automatic
model-to-DTO conversion. Tag your own `build` and it takes over:

```python hl_lines="2 4"
class TaskRefRepository(Repository[Task, str]):
    @on("hydrate", mode="build")
    def title(self, model: Task) -> str:
        return model.title


repo.get(task_id)   # str | None, not a Task
```

Unlike `before` and `after`, which chain, `build` has a single winner: the
most-derived `build` runs and the base default steps aside. `after` hooks still
fire on top of whatever `build` returned, so you can replace the construction
and enrich it.

This is the same job the [`_hydrate` override](custom-queries.md#custom-hydration)
does, and the two are interchangeable, defining `_hydrate` *is* the `build` hook
under the hood. Reach for the hook when the construction is a small, named thing;
reach for the override when it is a longer method you would rather spell out.

## Sharing hooks across repositories

More than one method can answer the same event, they all run, base classes
before subclasses. This is what makes a hook worth more than an override: a
concern that cuts across tables lives in a mixin once, and every repository that
inherits it gets the behavior, with no `super()` call to remember.

```python
class TimestampMixin:
    @on("create", mode="before")
    def set_created_at(self, model, payload) -> None:
        model.created_at = datetime.now(UTC)

    @on("update", mode="before")
    def set_updated_at(self, model, payload) -> None:
        model.updated_at = datetime.now(UTC)


class TaskRepository(TimestampMixin, Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    pass        # every write is timestamped, with no override anywhere


class WorkspaceRepository(TimestampMixin, Repository[Workspace, WorkspaceDTO, ...]):
    pass        # and so is this one
```

A single method can also serve several events, stack `@on`. One audit method for
create, update, and delete:

```python
class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    @on("create", mode="after")
    @on("update", mode="after")
    @on("delete", mode="after")
    def audit(self, model: Task) -> None:
        self.session.add(AuditEntry(task_id=model.id, at=datetime.now(UTC)))
```

## When a hook is not enough

Hooks add to, or replace, what the base already does. Some methods are not on the
base at all, a free-text search, a batch import, an `INSERT ... ON CONFLICT DO
UPDATE`. Those are plain methods you write with `self.session`; see
[custom methods](custom-queries.md). To give one the same `flush` / `commit` /
rollback the built-in writes get, decorate it with
[`@writes`](custom-queries.md#writes).
