---
icon: lucide/house
hide:
  - navigation
  - toc
---

# repositron

<p style="font-size: 1.25rem; opacity: 0.8;">
A typed, generic repository base for SQLAlchemy 2.0.<br>
Full CRUD, with <strong>zero per-table boilerplate</strong>.
</p>

[Get started](get-started.md){ .md-button .md-button--primary }
[Guides](guides/index.md){ .md-button }

---

Every SQLAlchemy project ends up with the same folder: one repository class per
table, each wrapping `select(...)` / `session.scalars(...)` in the same `get`,
the same `list`, the same pagination math. repositron writes that layer once,
generically, and types it against your model and your return shape.

=== ":material-close-circle: Hand-written, per table"

    ```python
    from sqlalchemy import select


    class TaskRepository:
        def __init__(self, session: Session) -> None:
            self.session = session

        def get(self, id: int) -> TaskDTO | None:
            row = self.session.scalars(select(Task).where(Task.id == id)).first()
            if row is None:
                return None
            return TaskDTO(id=row.id, title=row.title, status=row.status, assignee_id=row.assignee_id)

        def list(self, *, status: str | None = None) -> list[TaskDTO]:
            stmt = select(Task)
            if status is not None:
                stmt = stmt.where(Task.status == status)
            rows = self.session.scalars(stmt).all()
            return [TaskDTO(id=r.id, title=r.title, status=r.status, assignee_id=r.assignee_id) for r in rows]

        def update(self, id: int, *, assignee_id: int | None = None) -> bool:
            task = self.session.scalars(select(Task).where(Task.id == id)).first()
            if task is None:
                return False
            if assignee_id is not None:   # and how do you unassign on purpose?
                task.assignee_id = assignee_id
            self.session.flush()
            return True

        # ...count, delete, first, pagination, then again for the next ten tables.
    ```

=== ":material-check-circle: Declared once"

    ```python
    from dataclasses import dataclass
    from repositron import Repository, UNSET, UnsetType


    @dataclass(frozen=True, slots=True)
    class TaskDTO:               # light, detached, serializes straight to JSON
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
        title: str | UnsetType = UNSET            # absent leaves it; None sets NULL
        status: str | UnsetType = UNSET
        assignee_id: int | None | UnsetType = UNSET


    class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
        ...
    ```

    Every method from the other tab now exists, typed against `TaskDTO`, with no
    further code.

## What you get

<div class="grid cards" markdown>

-   :material-shield-check:{ .lg .middle } __Typed end to end__

    ---

    `repo.list()` is `list[TaskDTO]`, and your editor knows it. No casts, no
    `Any`. The return value is the same object your API serializes.

-   :material-filter-variant:{ .lg .middle } __Two ways to filter, one call__

    ---

    Equality by keyword and arbitrary SQLAlchemy expressions, combined. You never
    pick between readable and powerful.

    [:octicons-arrow-right-24: Filtering](guides/filtering.md)

-   :material-null:{ .lg .middle } __Updates that write NULL on purpose__

    ---

    `UNSET` leaves a column alone; `None` sets it to `NULL`. The `is not None`
    pattern cannot tell those apart. repositron can.

    [:octicons-arrow-right-24: Updating rows](guides/updates.md)

-   :material-table-column:{ .lg .middle } __Load only what you need__

    ---

    `repo[Card].list()` selects just that shape's columns, for one call, without
    touching the injected repository.

    [:octicons-arrow-right-24: Projection](guides/projection.md)

-   :material-book-open-page-variant:{ .lg .middle } __Pagination that refuses to lie__

    ---

    `list_paginated` requires `order_by` and raises if you forget, turning a
    production heisenbug into an error at the call site.

    [:octicons-arrow-right-24: Pagination](guides/pagination.md)

-   :material-feather:{ .lg .middle } __One dependency__

    ---

    Just `sqlalchemy>=2.0`. Dataclass DTOs add nothing else; Pydantic is detected
    only if your DTO is one.

</div>

## Install { style="text-align: center" }

<div style="max-width: 22rem; margin: 0 auto;" markdown>

=== "uv"

    ```bash
    uv add repositron
    ```

=== "pip"

    ```bash
    pip install repositron
    ```

</div>

<p style="text-align: center;">Python 3.13+ and <code>sqlalchemy>=2.0</code>.</p>

[Get started](get-started.md){ .md-button .md-button--primary }
{ style="text-align: center" }
