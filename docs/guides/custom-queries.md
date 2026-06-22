---
icon: lucide/function-square
---

# Custom queries

The base class gives you CRUD. Real repositories grow past CRUD: a free-text
search, a batch insert, a query that joins three tables to answer one question.
repositron's job is to remove the boilerplate, not to box you in, so everything
on your repository is an ordinary class with `self.session` and `self.model_class`
to build on.

??? note "Setup"

    The examples below all share one task-tracker domain: a `Task` model, its
    DTOs and payloads, a `TaskRepository`, and two extra models (`Member`,
    `Subtask`) that some examples join against or write to.

    ```python
    from __future__ import annotations

    from dataclasses import dataclass
    from datetime import datetime

    from sqlalchemy import ForeignKey
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    from repositron import Repository, UNSET, UnsetType


    class Base(DeclarativeBase): ...


    class Task(Base):
        __tablename__ = "tasks"

        id: Mapped[int] = mapped_column(primary_key=True)
        workspace_id: Mapped[int]
        title: Mapped[str]
        description: Mapped[str | None] = mapped_column(default=None)
        status: Mapped[str] = mapped_column(default="open")
        assignee_id: Mapped[int | None] = mapped_column(default=None)
        created_at: Mapped[datetime] = mapped_column(default=datetime.now)
        archived_at: Mapped[datetime | None] = mapped_column(default=None)


    class Member(Base):
        __tablename__ = "members"

        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str]


    class Subtask(Base):
        __tablename__ = "subtasks"

        id: Mapped[int] = mapped_column(primary_key=True)
        task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
        title: Mapped[str]


    @dataclass
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
        description: str | None | UnsetType = UNSET
        status: str | UnsetType = UNSET
        assignee_id: int | None | UnsetType = UNSET


    class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]): ...
    ```

## Domain queries

A method that does not fit `get` / `list` is just a method. You have the session,
the model, and the full SQLAlchemy API:

```python
from datetime import datetime

from sqlalchemy import update


class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    def open_in_workspace(self, workspace_id: int) -> list[TaskDTO]:
        return self.list(status="open", workspace_id=workspace_id)

    def archive_all_done(self, workspace_id: int) -> None:
        self.session.execute(
            update(Task)
            .where(Task.workspace_id == workspace_id, Task.status == "done")
            .values(archived_at=datetime.now())
        )
        self.session.flush()
```

Note the first method reuses `self.list` instead of reaching for the session.
Build on the inherited methods where they fit; drop to raw SQLAlchemy only where
they do not.

## Filter builders { #filter-builders }

When the same `WHERE` fragment shows up in several calls, a free-text search being
the classic case, give it a name. A method that returns a SQLAlchemy expression
plugs straight into `extra_filters`:

```python
from sqlalchemy import ColumnElement, or_


class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    def search(self, q: str) -> ColumnElement[bool]:
        pattern = f"%{q}%"
        return or_(
            Task.title.ilike(pattern),
            Task.description.ilike(pattern),
        )


repo.list(extra_filters=[repo.search("deploy")], status="open")
```

Callers express intent ("search for deploy") and the column logic lives in one
place.

## Batch inserts

`create` inserts one row and reads its key back. For importing many rows at once,
the per-row flush is the wrong tool. Add a batch method that uses
`session.add_all` and flushes once:

```python
class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    def create_many(self, payloads: list[TaskCreate]) -> None:
        if not payloads:
            return
        rows = [Task(workspace_id=p.workspace_id, title=p.title) for p in payloads]
        self.session.add_all(rows)
        self.session.flush()
```

The same shape works for a batch that needs the generated ids back, by reading
them off the flushed models:

```python
    def create_many_returning(self, payloads: list[TaskCreate]) -> list[int]:
        rows = [Task(workspace_id=p.workspace_id, title=p.title) for p in payloads]
        self.session.add_all(rows)
        self.session.flush()
        return [r.id for r in rows]
```

## Custom hydration { #custom-hydration }

The automatic model-to-DTO conversion handles the common cases: a dataclass built
by field name, a Pydantic model through `model_validate`, or the model returned
as-is.

For the rest, the question is *add* or *replace*:

- To **add** a derived field to the built DTO, use a [`hydrate` hook](hooks.md#enriching-the-dto).
  It hands you the finished DTO to enrich, so you write one field, not all of them.
- To **replace** the build, when the automatic path cannot produce the DTO at
  all, override `_hydrate` and construct it yourself:

```python
from dataclasses import dataclass

from sqlalchemy import select


@dataclass
class TaskDetail:
    id: int
    title: str
    status: str
    assignee_name: str | None   # rolled up from Member, not a column on Task


class TaskRepository(Repository[Task, TaskDetail]):
    def _hydrate(self, model: Task) -> TaskDetail:
        assignee_name = self.session.scalars(
            select(Member.name).where(Member.id == model.assignee_id)
        ).first()
        return TaskDetail(
            id=model.id,
            title=model.title,
            status=model.status,
            assignee_name=assignee_name,
        )
```

`_hydrate` then runs for every read, so `get`, `first`, and `list` all return
fully-formed `TaskDetail` objects. (Column projection via `repo[Shape]` builds
the narrow shape positionally and does not go through `_hydrate`, which keeps a
projection a pure column read.)

Overriding `_hydrate` and tagging a method with
[`@on("hydrate", mode="build")`](hooks.md#replacing-the-build) are the same
mechanism, the override is just the build hook spelled as a method. Use whichever
reads better: the override for a longer construction like the one above, the hook
for a one-liner.

## Transactions on custom writes { #writes }

A custom write is responsible for the same `flush` / `commit` / rollback dance
the built-in `create` / `update` / `delete` handle for you. `@writes` gives a
custom method that dance, so its body is only the session work:

```python hl_lines="7"
from sqlalchemy import update

from repositron import Repository, writes


class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    @writes
    def bulk_set_status(self, task_ids: list[int], status: str) -> None:
        self.session.execute(
            update(Task).where(Task.id.in_(task_ids)).values(status=status)
        )   # flushed for you; rolled back on error
```

The decorated method flushes after the body, commits if the repository is
`autocommit=True`, and rolls back on error, exactly like the built-in writes (see
[committing](updates.md#transactions)). To let a caller commit a single write,
declare a `commit` parameter and `@writes` honors it:

```python
    @writes
    def bulk_set_status(
        self, task_ids: list[int], status: str, *, commit: bool | None = None
    ) -> None:
        self.session.execute(
            update(Task).where(Task.id.in_(task_ids)).values(status=status)
        )


repo.bulk_set_status([1, 2, 3], "done", commit=True)   # this one write commits
```

When the method needs the primary key mid-way, to attach child rows or return it,
flush yourself at that point. `@writes` still owns the final flush and the
commit/rollback:

```python
    @writes
    def create_with_subtasks(self, payload: TaskCreate, subtasks: list[str]) -> int:
        task = Task(workspace_id=payload.workspace_id, title=payload.title)
        self.session.add(task)
        self.session.flush()        # need task.id for the subtasks below
        for title in subtasks:
            self.session.add(Subtask(task_id=task.id, title=title))
        return task.id
```

Without `@writes`, a custom write should still `flush`, never `commit`, the same
as the base class, so it composes inside the caller's transaction. See the
[design principles](../reference.md#design-principles).
