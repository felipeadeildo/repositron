---
icon: lucide/pencil
---

# Updating rows

This is the feature people do not notice until the day it would have saved them.

??? note "Setup"

    ```python
    from dataclasses import dataclass
    from datetime import datetime

    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
    from repositron import UNSET, UnsetType, Repository


    class Base(DeclarativeBase): ...


    class Task(Base):
        __tablename__ = "tasks"

        id: Mapped[int] = mapped_column(primary_key=True)
        workspace_id: Mapped[int]
        title: Mapped[str]
        description: Mapped[str | None]
        status: Mapped[str] = mapped_column(default="open")
        assignee_id: Mapped[int | None]
        created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
        archived_at: Mapped[datetime | None]


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
        assignee_id: int | None | UnsetType = UNSET   # None means unassign


    class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]): ...


    repo = TaskRepository(session)
    ```

## The blind spot in the usual pattern

Almost every hand-written partial update looks like this:

```python
if title is not None:
    task.title = title
if assignee_id is not None:
    task.assignee_id = assignee_id
```

It reads fine, and it is wrong in one specific way: it cannot set a column to
`NULL`. "The caller did not mention this field" and "the caller wants this field
cleared" both arrive as `None`, and the `is not None` guard collapses them into
the same branch. There is no way through this code to unassign a task, set
`assignee_id` back to `NULL`, because that intent and "leave the assignee alone"
look identical. To null a column on purpose you have to invent a second
convention, and now your update path has two ways to say "change nothing".

## Two sentinels, two meanings

repositron keeps the two intents apart with a dedicated sentinel:

| You pass        | Meaning                 | Result            |
| --------------- | ----------------------- | ----------------- |
| `UNSET`         | leave this column alone | column unchanged  |
| `None`          | set this column to NULL | `column = NULL`   |
| any other value | set it                  | `column = value`  |

You opt in by defaulting your update fields to `UNSET`:

```python
from dataclasses import dataclass
from repositron import UNSET, UnsetType


@dataclass
class TaskUpdate:
    title: str | UnsetType = UNSET
    status: str | UnsetType = UNSET
    assignee_id: int | None | UnsetType = UNSET   # None is a real, allowed value here
```

Now the three outcomes are all expressible, and they read exactly as they mean:

```python hl_lines="2"
repo.update(1, TaskUpdate(status="done"))      # assignee untouched
repo.update(1, TaskUpdate(assignee_id=None))   # unassign: assignee_id becomes NULL
repo.update(1, TaskUpdate())                    # a no-op write
```

Under the hood, `update` walks the payload's fields, skips any that are still
`UNSET`, and writes the rest, `None` included. A field left at its `UNSET`
default never appears in the `UPDATE` statement at all.

## UNSET on create, too

The same sentinel is useful on the create side, for a different reason. A field
left `UNSET` is simply omitted from the insert, which lets the column's database
default (or the model's) take over instead of you hard-coding it in the payload:

```python
@dataclass
class TaskCreate:
    workspace_id: int
    title: str
    description: str | None | UnsetType = UNSET   # omit it -> the column default applies
    assignee_id: int | None | UnsetType = UNSET


repo.create(TaskCreate(workspace_id=1, title="Ship docs"))   # description uses its default
repo.create(TaskCreate(workspace_id=1, title="Ship docs", description="for the v0.3 release"))
```

This is handy at the boundary between an HTTP layer and the repository: an
optional request field that was not provided maps cleanly to `UNSET`, and the
database fills in what it always would have.

```python
payload = TaskCreate(
    workspace_id=body.workspace_id,
    title=body.title,
    description=body.description if body.description is not None else UNSET,
)
```

## Return value

`update` returns `True` on success and `False` when no row has that primary key,
so a missing record is an ordinary boolean to handle, not an exception to catch:

```python
# NotFound is your application's own exception, e.g. mapped to an HTTP 404.
if not repo.update(task_id, TaskUpdate(status="done")):
    raise NotFound(task_id)
```

`delete` follows the same convention. `create` returns the new primary key.

## Committing { #transactions }

Writes `flush` by default: visible in your session, but not committed, so the
transaction boundary stays in your app. Opt into committing per instance or per
call.

```python
repo = TaskRepository(session, autocommit=True)   # every write commits
repo.create(TaskCreate(workspace_id=1, title="Ship docs"))

task_id = repo.create(TaskCreate(workspace_id=1, title="Index attachments"), commit=True)   # just this one
worker.enqueue(task_id)   # a separate process only sees committed rows
```

`commit=` overrides the instance default both ways.

| `autocommit` | `commit=` | Result               |
| ------------ | --------- | -------------------- |
| `False`      | `None`    | flush only (default) |
| any          | `True`    | commit this write    |
| any          | `False`   | flush this write only |
| `True`       | `None`    | commit every write   |

### On error

A failed flush or commit rolls the session back before re-raising, so it stays
usable. Turn it off to keep the session as-is and roll back yourself:

```python
Repository(session, rollback_on_error=False)
```
