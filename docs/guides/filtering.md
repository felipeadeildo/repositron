---
icon: lucide/filter
---

# Filtering

Most queries are a `WHERE` clause and an `ORDER BY`. repositron gives you two
ways to write the `WHERE`, and they live in the same call, so you never have to
choose between the readable one and the powerful one.

??? note "Setup"

    The examples on this page share one task-tracker domain: a `Task` model
    scoped to a workspace, with a soft-delete `archived_at` column.

    ```python
    import datetime
    from dataclasses import dataclass

    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    from repositron import Repository, UNSET, UnsetType


    class Base(DeclarativeBase): ...


    class Task(Base):
        __tablename__ = "tasks"
        id: Mapped[int] = mapped_column(primary_key=True)
        workspace_id: Mapped[int]
        title: Mapped[str]
        description: Mapped[str | None] = mapped_column(default=None)
        status: Mapped[str] = mapped_column(default="open")  # open | in_progress | done
        assignee_id: Mapped[int | None] = mapped_column(default=None)
        created_at: Mapped[datetime.datetime]
        archived_at: Mapped[datetime.datetime | None] = mapped_column(default=None)


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


    class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
        ORDER = [Task.created_at.desc(), Task.id]


    repo = TaskRepository(session)
    ```

## Equality reads as keyword arguments

The common case is matching a column to a value. Pass it as a keyword argument,
keyed by the model's attribute name:

```python
repo.list(status="open")
repo.list(status="open", workspace_id=42)
```

Each keyword becomes a `column == value` and they join with `AND`. If you name a
keyword that is not an attribute on the model, that is a `ValueError` at the call
site, not a silent empty result.

## Everything else is a SQLAlchemy expression

Equality covers a lot, but not comparisons, `IN`, `LIKE`, or `OR`. For those,
hand repositron the real SQLAlchemy expressions through `extra_filters`. It is a
list, and every entry is `AND`-ed in alongside the keyword filters:

```python hl_lines="7"
import datetime

cutoff = datetime.datetime.now() - datetime.timedelta(days=7)

repo.list(
    workspace_id=42,
    extra_filters=[
        Task.created_at >= cutoff,
        Task.archived_at.is_(None),
    ],
)
# WHERE workspace_id = 42
#   AND created_at >= :cutoff
#   AND archived_at IS NULL
```

Because `extra_filters` is just SQLAlchemy, anything the ORM can express fits,
including `OR` and `IN` over a list you built at runtime:

```python
from sqlalchemy import or_

wanted_ids = [101, 102, 103]
repo.list(extra_filters=[Task.id.in_(wanted_ids)])

q = "%deploy%"
repo.list(extra_filters=[or_(Task.title.ilike(q), Task.description.ilike(q))])
```

That last pattern, a free-text search across a couple of columns, is common
enough that it is worth wrapping in a method on your repository so callers do not
repeat it. See [custom methods](custom-queries.md#filter-builders) for that.

## The two special filter values

A keyword filter understands two values beyond the obvious:

| You pass | Meaning |
| -------- | ------- |
| `None`   | filter by `IS NULL` |
| `UNSET`  | skip this filter entirely |

`None` filtering by `IS NULL` is what you would hope for:

```python
repo.list(assignee_id=None)   # WHERE assignee_id IS NULL  (unassigned tasks)
```

`UNSET` is the quietly useful one. It means "pretend I did not pass this filter
at all", which removes the branching from any endpoint that forwards optional
query parameters:

```python
from typing import Annotated

from fastapi import Depends

from repositron import UNSET, UnsetType


@app.get("/workspaces/{workspace_id}/tasks")
def list_tasks(
    workspace_id: int,
    repo: Annotated[TaskRepository, Depends(get_repo)],
    assignee_id: int | None = None,
    status: str | UnsetType = UNSET,
):
    # status defaults to UNSET, so no filter is applied unless the caller set it.
    # assignee_id=None would filter by IS NULL (unassigned), which is a different
    # intent, so we only forward it when present.
    filters = {"status": status}
    if assignee_id is not None:
        filters["assignee_id"] = assignee_id
    return repo.list(workspace_id=workspace_id, **filters)
```

No ladder of `if param is not None`. The sentinel does the deciding.

## Ordering

`list` and `first` are unordered unless you ask. `order_by` takes one column or a
list of them:

```python
repo.list(order_by=Task.created_at.desc())
repo.list(order_by=[Task.created_at.desc(), Task.id])
```

A tidy habit from real codebases: when a table has one canonical sort, declare it
once as a class attribute and reuse it everywhere.

```python
class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
    ORDER = [Task.created_at.desc(), Task.id]

repo.list(order_by=repo.ORDER)
```

Ordering becomes mandatory the moment you paginate. That is the subject of the
[pagination recipe](pagination.md).
