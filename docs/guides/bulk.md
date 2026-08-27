---
icon: lucide/layers
---

# Bulk writes

`create`, `update`, and `delete` each touch one row and run its hooks. That is
the right shape for a request that edits a single record, and the wrong one for
work measured in rows: importing a thousand tasks, archiving every done task in a
workspace, clearing a tag off a batch. Looping the per-row methods means a flush
and a hook pass per row.

`update_where` and `delete_where` issue one set-based SQL statement. `bulk_create`
creates ORM models and flushes them together once, which preserves generated keys
and can use SQLAlchemy's insert batching when the dialect supports it.

??? note "Setup"

    ```python
    from dataclasses import dataclass

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
    from repositron import UNSET, UnsetType, Repository


    class Base(DeclarativeBase): ...


    class Task(Base):
        __tablename__ = "tasks"

        id: Mapped[int] = mapped_column(primary_key=True)
        workspace_id: Mapped[int]
        title: Mapped[str]
        status: Mapped[str] = mapped_column(default="open")
        assignee_id: Mapped[int | None] = mapped_column(default=None)


    @dataclass
    class TaskCreate:
        workspace_id: int
        title: str
        assignee_id: int | None | UnsetType = UNSET


    class TaskRepository(Repository[Task, Task, TaskCreate, object, int, AsyncSession]): ...


    repo = TaskRepository(session)
    ```

## Inserting many rows

`bulk_create` takes a list of the same payloads `create` takes, builds every
model, and flushes once. It returns the new primary keys in payload order. It
does not promise one `INSERT` statement; the dialect and SQLAlchemy choose how
to send the batch:

```python
ids = await repo.bulk_create([
    TaskCreate(workspace_id=1, title="Write the spec"),
    TaskCreate(workspace_id=1, title="Review the spec"),
    TaskCreate(workspace_id=1, title="Ship the spec"),
])
# ids == [1, 2, 3]
```

`UNSET` works exactly as it does on `create`: a field left at its `UNSET` default
is omitted from the insert, so the column or model default applies. See
[Updating rows](updates.md#unset-on-create-too) for the full story on `UNSET`.

An empty list is a no-op that returns `[]`, so you can hand it the result of a
filter without guarding for the empty case yourself.

## Updating and deleting in place

`update_where` and `delete_where` issue one `UPDATE` / `DELETE` against every row
that matches, without loading a single model. Filters are positional SQLAlchemy
expressions; for `update_where`, the new column values are keyword arguments. Both
return the number of rows the statement touched:

```python
# Archive every done task in a workspace.
n = await repo.update_where(
    Task.workspace_id == 1,
    Task.status == "done",
    status="archived",
)   # n == rows updated

# Reassign a whole workspace to one owner.
await repo.update_where(Task.workspace_id == 1, assignee_id=7)

# Drop every task assigned to a member who left.
removed = await repo.delete_where(Task.assignee_id == 42)
```

Because they speak in filters and values rather than instances, positional
arguments select rows and keyword arguments set column values:

```python linenums="1" hl_lines="2-3"
updated = await repo.update_where(
    Task.status == "open",  # (1)!
    status="in_progress",  # (2)!
)
```

1. This positional SQLAlchemy expression becomes the `WHERE` clause. It picks
   the rows to change.
2. This keyword argument becomes the `SET` clause. It supplies the new value.

`delete_where` has no `SET` clause to claim its keywords, so it accepts the same
equality `**filters` the read methods do, mixed freely with positional
expressions:

```python
await repo.delete_where(status="open")
await repo.delete_where(Task.created_at < cutoff, status="open")
```

### The empty-filter guard

Calling either method with no filters would mean "every row in the table", which
is almost never what a caller meant to type. Both raise `ValueError` rather than
silently rewriting or emptying the table:

```python
await repo.update_where(status="archived")  # ValueError: requires at least one filter
await repo.delete_where()                   # ValueError: requires at least one filter
```

To act on the whole table on purpose, say so with a filter that matches it, e.g.
`update_where(Task.id.is_not(None), ...)`.

## Hooks: off by default

This is the trade these methods make for their speed. `bulk_create`,
`update_where`, and `delete_where` do not run [`@on` hooks](hooks.md) the way the
per-row writes do.

For `update_where` and `delete_where` there is nothing to run a hook *on*: no
model is loaded, so a `("update", "before")` hook that expects a model instance
has none to receive. That is inherent to a set-based statement, and the reason to
reach for these methods at all.

`bulk_create` does build model instances, so it *can* fire the create hooks, but
it skips them by default to keep one ORM flush. When a payload genuinely needs
its create hooks, opt in with `hooks=True`:

```python
ids = await repo.bulk_create(payloads, hooks=True)
```

With `hooks=True`, each `("create", "before")` hook runs before the batch is
added, and each `("create", "after")` hook runs after the single flush. It is a
loop again, so reach for it only when the hooks earn it.

## Committing { #transactions }

All three flush and leave the commit to you, exactly like the per-row writes. Pass
`commit=True` for one call, or set `autocommit=True` on the instance; see
[committing](updates.md#transactions) for the full table.

```python
await repo.bulk_create(payloads, commit=True)
await repo.update_where(Task.status == "done", status="archived", commit=True)
```

## When not to use these

These methods cover the common bulk shapes. Anything past them, an upsert, a
batch where each row sets different values, a write that joins, is a
[custom query](custom-queries.md): drop to raw SQLAlchemy with `@writes` to keep
the same flush / commit / rollback handling.
