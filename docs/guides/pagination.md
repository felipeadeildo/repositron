---
icon: lucide/book-open
---

# Pagination

Pagination is the place where a small oversight turns into a bug that only shows
up in production, under load, for some users, some of the time. repositron is
opinionated here on purpose.

??? note "Setup"

    ```python
    from __future__ import annotations

    from dataclasses import dataclass
    from datetime import datetime

    from sqlalchemy import DateTime, Integer, String
    from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

    from repositron import Repository


    class Base(DeclarativeBase): ...


    class Task(Base):
        __tablename__ = "tasks"

        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        workspace_id: Mapped[int] = mapped_column(Integer)
        title: Mapped[str] = mapped_column(String)
        description: Mapped[str | None] = mapped_column(String, default=None)
        status: Mapped[str] = mapped_column(String, default="open")  # open|in_progress|done
        assignee_id: Mapped[int | None] = mapped_column(Integer, default=None)
        created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
        archived_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


    @dataclass(frozen=True, slots=True)
    class TaskDTO:
        id: int
        title: str
        status: str
        assignee_id: int | None


    class TaskRepository(Repository[Task, TaskDTO, "TaskCreate", "TaskUpdate"]):
        ORDER = [Task.created_at.desc(), Task.id]


    session: Session = ...  # your SQLAlchemy session
    repo = TaskRepository(session)
    ```

## A page and its total

`list_paginated` returns a `PaginatedResult`: the slice of rows for this page,
plus the total the query would return without the offset and limit. That total
is what you need to compute how many pages there are, so it comes back in the
same call rather than forcing a second one.

```python
page = repo.list_paginated(offset=0, limit=20, order_by=Task.created_at.desc())

page.items   # list[TaskDTO]  -> this page
page.total   # int            -> all matching rows, ignoring offset/limit
```

It takes the same `extra_filters` and `**filters` as `list`, so filtering and
paginating compose exactly the way you would expect. Here we page through the
open tasks in one workspace, newest first:

```python
offset, limit = 0, 20

page = repo.list_paginated(
    offset=offset,
    limit=limit,
    workspace_id=42,
    status="open",
    order_by=repo.ORDER,
)

page.items   # list[TaskDTO]  -> up to 20 open tasks in workspace 42
page.total   # int            -> every open task in workspace 42
```

A typical service method wraps it and maps `total` into whatever your API's page
envelope looks like:

```python
from repositron import PaginatedResult


def list_open_tasks(self, workspace_id: int, offset: int, limit: int):
    result: PaginatedResult[TaskDTO] = self.repo.list_paginated(
        offset=offset,
        limit=limit,
        workspace_id=workspace_id,
        status="open",
        order_by=self.repo.ORDER,
    )
    return {
        "items": result.items,
        "total": result.total,
        "offset": offset,
        "limit": limit,
    }
```

## From a web request

Most callers receive a `page`/`size` query and translate it into `offset`/`limit`.
A FastAPI endpoint with the repository injected looks like this:

```python hl_lines="19"
from typing import Annotated

from fastapi import Depends, FastAPI

app = FastAPI()


def get_repo(session: Annotated[Session, Depends(get_session)]) -> TaskRepository:
    return TaskRepository(session)


@app.get("/workspaces/{workspace_id}/tasks")
def list_tasks(
    workspace_id: int,
    repo: Annotated[TaskRepository, Depends(get_repo)],
    page: int = 1,
    size: int = 20,
):
    result = repo.list_paginated(
        offset=(page - 1) * size,
        limit=size,
        workspace_id=workspace_id,
        status="open",
        order_by=repo.ORDER,
    )
    return {"items": result.items, "total": result.total, "page": page, "size": size}
```

`get_repo` is your dependency-injection provider; `get_session` is whatever yields
a request-scoped `Session`.

## Why order_by is required

Here is the part that is not optional. `list_paginated` will raise a `ValueError`
if you do not give it an `order_by`:

```python
repo.list_paginated(0, 20)                              # ValueError
repo.list_paginated(0, 20, order_by=Task.created_at)    # fine
```

This is deliberate. A database is free to return rows in any order when you do
not specify one, and that order can differ between two queries that are otherwise
identical. Page through such a result and rows silently shift across page
boundaries: some appear twice, some never appear at all. Nothing errors. The
counts even look right. You find out from a user asking where a record went.

repositron turns that quiet data bug into a loud error at the call site, the
moment you write the query, where it costs you ten seconds instead of a debugging
session. Pick a stable order, ideally one that ends in a unique column like the
primary key, and the problem cannot occur:

```python
repo.list_paginated(0, 20, order_by=[Task.created_at.desc(), Task.id])
```

## Pagination plays well with projection

Paginating a wide table while only showing a few columns is a natural pairing.
Project first, then paginate, and you fetch only what the page renders:

```python
@dataclass(frozen=True, slots=True)
class TaskCard:
    id: int
    title: str
    status: str


page = repo[TaskCard].list_paginated(
    0, 20, workspace_id=42, status="open", order_by=repo.ORDER
)
# SELECT only TaskCard's columns, paginated -> PaginatedResult[TaskCard]
```

See the [projection recipe](projection.md) for what `repo[TaskCard]` does.
