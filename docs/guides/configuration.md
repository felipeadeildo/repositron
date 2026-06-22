---
icon: lucide/sliders-horizontal
---

# Configuration

A repository is configured in three places: the **type parameters** it inherits
with, the **class attributes** it sets, and the **hooks** it declares with `@on`.
This page is the full map of what you can change and how each piece behaves. Most
repositories touch only the first two.

??? note "Setup (models and DTO used throughout this page)"

    ```python
    from dataclasses import dataclass
    from datetime import datetime

    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    from repositron import Repository


    class Base(DeclarativeBase):
        pass


    class Task(Base):
        __tablename__ = "tasks"

        id: Mapped[int] = mapped_column(primary_key=True)
        workspace_id: Mapped[int]
        title: Mapped[str]
        description: Mapped[str | None]
        status: Mapped[str]
        assignee_id: Mapped[int | None]
        created_at: Mapped[datetime]
        archived_at: Mapped[datetime | None]


    @dataclass(frozen=True, slots=True)
    class TaskDTO:
        id: int
        title: str
        status: str
        assignee_id: int | None


    @dataclass(frozen=True, slots=True)
    class TaskCreate:
        workspace_id: int
        title: str
        status: str


    @dataclass(frozen=True, slots=True)
    class TaskUpdate:
        title: str | None = None
        status: str | None = None
        assignee_id: int | None = None


    class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]):
        pass
    ```

## The one idea: convention first, configuration only when you diverge

Here is the mental model that makes the rest of this page obvious.

By default, **repositron expects your DTO to mirror your model**: the same field
names, the same types. When that holds, nothing needs configuring. You declare
the DTO, inherit the repository, and hydration just works, field by matching
field.

```python
from dataclasses import dataclass

from sqlalchemy.orm import Mapped, mapped_column

from repositron import Repository


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    status: Mapped[str]


@dataclass(frozen=True, slots=True)
class TaskDTO:        # same names, same types as the columns
    id: int
    title: str
    status: str


class TaskRepository(Repository[Task, TaskDTO]):
    pass             # no field_mapping, no overrides, nothing
```

That `pass` is the point. The common case has zero configuration.

You only reach for the knobs below when the DTO needs to **diverge** from the
model:

- a field is named differently from its column? add it to `field_mapping`
- the DTO should carry fewer columns than the model? just leave them out, and the
  extra columns are simply not read into it
- the DTO needs a value the row alone cannot give (a join, a computed field)?
  add it with a [`hydrate` hook](hooks.md#enriching-the-dto)
- the primary key is not called `id`? set `pk_column`

So the beauty is the gradient: the zero-config path covers most tables, and every
divergence has exactly one small place to express it. You pay for flexibility
only on the tables that need it.

## Type parameters and their defaults

```python
Repository[Model, DTO = Model, Create = object, Update = object, PK = int]
ReadOnlyRepository[Model, DTO = Model, PK = int]
```

Only `Model` is required. Everything after it has a default, so you supply each
parameter only when you actually need it.

| Parameter | If you omit it...                                              |
| --------- | ------------------------------------------------------------- |
| `Model`   | required; this is the SQLAlchemy class the repository queries |
| `DTO`     | defaults to `Model`: reads return the model itself, unhydrated |
| `Create`  | defaults to `object`: you simply do not call `create`         |
| `Update`  | defaults to `object`: you simply do not call `update`         |
| `PK`      | defaults to `int`: the type of the primary key, so `get`/`exists`/`delete` take it and `create` returns it |

That is why both of these are valid, each adding only what it uses:

```python
from dataclasses import dataclass

from sqlalchemy.orm import Mapped, mapped_column

from repositron import ReadOnlyRepository, Repository


# Full CRUD over Task, int key, hydrating to TaskDTO with payloads.
class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]): ...


# Read-only cache table keyed by a string hash, hydrating to PageDTO.
class Page(Base):
    __tablename__ = "pages"

    url_hash: Mapped[str] = mapped_column(primary_key=True)
    html: Mapped[str]


@dataclass(frozen=True, slots=True)
class PageDTO:
    url_hash: str
    html: str


class PageRepository(ReadOnlyRepository[Page, PageDTO, str]):
    pk_column = "url_hash"
```

The key type lives in the last slot so the int-keyed majority never writes it.
When the key is a `str` or `uuid`, declare it there, see
[primary keys](primary-keys.md) for the why and the slot mechanics.

The parameters are read off your class declaration at runtime, so you do not
register the model or wire anything up. Inheriting with the types *is* the
configuration. (If you forget to parameterize, repositron raises a clear
`TypeError` telling you to pass the generic arguments.)

## `field_mapping`: when a DTO field is named differently { #field_mapping }

The most common reason a DTO cannot be built automatically is a name mismatch:
the column is `created_at`, but your DTO (and your API) calls it `opened_at`.
`field_mapping` records that rename once.

The direction is **`{model_column: dto_field}`**, read as "the model's
`created_at` is the DTO's `opened_at`":

```python
class TaskRepository(Repository[Task, TaskDTO]):
    field_mapping = {"created_at": "opened_at"}
```

```python
from datetime import datetime

from sqlalchemy.orm import Mapped


class Task(Base):
    created_at: Mapped[datetime]    # the column

@dataclass
class TaskDTO:
    opened_at: datetime             # the field
```

### It applies in both directions

This is the part worth internalizing: one mapping covers every direction data
flows through the repository.

- **Reading (hydration).** When a row becomes a `TaskDTO`, the column `created_at`
  is read into the field `opened_at`.
- **Projecting.** When you do `repo[TaskCard].list()` and `TaskCard` has an
  `opened_at` field, repositron resolves it back to the `created_at` column to
  build the `SELECT`. See [projection](projection.md).
- **Writing.** Create and update payloads are matched against model attributes by
  name, so a payload field that matches a real column writes straight through.

You declare the rename in one place and never think about which direction you are
going. A field not listed in `field_mapping` is assumed to have the same name on
both sides, which is the usual case, so the map only ever holds the exceptions.

## `pk_column`: when the key is not `id`

The base assumes the key column is named `id`. When it is not, set `pk_column`,
either to the column name or to the column reference itself, and every id-based
method follows:

```python
from dataclasses import dataclass

from sqlalchemy.orm import Mapped, mapped_column

from repositron import ReadOnlyRepository


class Page(Base):                 # a cache table keyed by a content hash
    __tablename__ = "pages"

    url_hash: Mapped[str] = mapped_column(primary_key=True)
    html: Mapped[str]


@dataclass(frozen=True, slots=True)
class PageDTO:
    url_hash: str
    html: str


class PageRepository(ReadOnlyRepository[Page, PageDTO, str]):
    pk_column = "url_hash"        # by name


class PageRepository(ReadOnlyRepository[Page, PageDTO, str]):
    pk_column = Page.url_hash     # by column reference (checked against the model)
```

The column's *name* is a runtime concern (`pk_column`); the key's *type* is the
last type parameter (`PK`). They are separate knobs. The details, including
`str`/`uuid` keys and composite keys, live in [primary keys](primary-keys.md).

## Defaults you can override at the class level

Beyond the two configured attributes, a common convention is to attach a
canonical ordering to the repository so callers do not repeat it:

```python
class TaskRepository(Repository[Task, TaskDTO]):
    field_mapping = {"created_at": "opened_at"}
    ORDER = [Task.created_at.desc(), Task.id]

repo.list(order_by=repo.ORDER)
repo.list_paginated(0, 20, order_by=repo.ORDER)
```

`ORDER` is not special to repositron, it is just an attribute you define and pass
in. But it is the idiomatic place to keep "the way this table is normally
sorted", so it is worth adopting.

## Adding behavior: hooks

When configuration is not enough because there is logic to run, a write that
needs a derived column, a DTO that needs an extra field, you add it with a
[hook](hooks.md), not an override. Tag a method with `@on` and the base runs it
inside its own `create` / `update` / `delete` / hydration:

```python
from dataclasses import replace

from repositron import Repository, on


class TaskRepository(Repository[Task, TaskDetail]):
    @on("hydrate", mode="after")
    def with_assignee(self, model: Task, dto: TaskDetail) -> TaskDetail:
        return replace(dto, assignee=self._load_assignee(model.assignee_id))
```

Overriding `_hydrate` is the rarer fallback, only when the automatic build cannot
produce the DTO at all. [Hooks](hooks.md) covers both, and where the line falls.

## The short version

| To change...                          | Do this                                  |
| ------------------------------------- | ---------------------------------------- |
| what reads return                     | set the `DTO` type parameter             |
| a field whose name differs from the column | add it to `field_mapping`           |
| the primary-key column name           | set `pk_column`                          |
| the default sort for callers          | set a class attribute like `ORDER`       |
| add a derived field, column, or side effect | a [hook](hooks.md) with `@on`     |
| build a DTO the automatic path can't  | override `_hydrate`                      |
