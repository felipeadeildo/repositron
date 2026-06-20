---
icon: lucide/book-marked
---

# API reference

Everything the package exposes, in one place. For task-oriented walkthroughs,
start with the [recipes](recipes/index.md).

## Imports

```python
from repositron import (
    Repository,            # full CRUD generic base
    ReadOnlyRepository,    # read-only generic base
    PaginatedResult,       # the {items, total} container
    OrderBy,               # the order_by argument type
    UNSET, UnsetType,      # the partial-update sentinel and its type
)
```

## Type parameters

```python
Repository[Model, DTO = Model, Create = object, Update = object, PK = int]
ReadOnlyRepository[Model, DTO = Model, PK = int]
```

`Model` is required. `DTO` defaults to the model itself (reads return the model,
unhydrated). `Create` and `Update` are the payload dataclasses your writes
accept. `PK` is the primary-key type, defaulting to `int`; declare it (last,
after the others) when your key is a `str` or `uuid`. So `Repository[Account]`
is a valid read/write repository returning `Account` with an `int` key, and you
add the other parameters only as you need them. See
[primary keys](recipes/primary-keys.md).

## Class attributes

Set these on your repository subclass.

| Attribute       | Type                            | Purpose                                       | Default |
| --------------- | ------------------------------- | --------------------------------------------- | ------- |
| `field_mapping` | `dict[str, str]`                | `{model_column: dto_field}` for renamed fields | `{}`    |
| `pk_column`     | `str \| InstrumentedAttribute`  | primary-key column, by name or column reference | `"id"`  |

```python
class UserRepository(Repository[User, UserDTO, UserCreate, UserUpdate]):
    field_mapping = {"full_name": "name"}
    pk_column = User.id   # or "id"
```

## Read methods

Available on both `ReadOnlyRepository` and `Repository`.

`get(id) -> DTO | None`
:   Fetch one row by primary key, hydrated to the DTO. `None` if absent.

`first(*, extra_filters=None, order_by=None, **filters) -> DTO | None`
:   The first row matching the filters, or `None`. See [filtering](recipes/filtering.md).

`list(*, extra_filters=None, order_by=None, **filters) -> list[DTO]`
:   All rows matching the filters, each hydrated to the DTO.

`list_paginated(offset, limit=20, *, extra_filters=None, order_by, **filters) -> PaginatedResult[DTO]`
:   A page plus the unpaginated total. `order_by` is **required**; omitting it
    raises `ValueError`. See [pagination](recipes/pagination.md).

`count(*, extra_filters=None, **filters) -> int`
:   Count of rows matching the filters.

`exists(id) -> bool`
:   Whether a row with this primary key exists.

`repo[Shape]`
:   A clone bound to `Shape` for the next call, triggering column projection when
    `Shape` is a narrow dataclass. See [projection](recipes/projection.md).

## Constructor

`Repository(session, *, autocommit=False, rollback_on_error=True)`
:   `session` is the caller-owned SQLAlchemy `Session`. With `autocommit=True`,
    every write commits after its flush; the default flushes only and leaves the
    transaction to you. `rollback_on_error` (`True` by default) rolls the session
    back before re-raising when a flush or commit fails; set it to `False` to
    leave that rollback to you. See
    [transactions](recipes/updates.md#transactions).

## Write methods

Available on `Repository` only. Each takes `commit: bool | None = None`: `None`
follows the instance's `autocommit`, `True`/`False` overrides it for that one
call. On a commit failure the session is rolled back and the error re-raised.

`create(payload, *, commit=None) -> PK`
:   Insert from a dataclass payload and flush. `UNSET` fields are omitted so the
    column default applies. Returns the new primary key, typed as the `PK`
    parameter (`int` by default).

`update(id, payload, *, commit=None) -> bool`
:   Partial-update from a dataclass payload and flush. `UNSET` fields are skipped;
    `None` is written as `NULL`. `False` if no row has that key. See
    [updates](recipes/updates.md).

`delete(id, *, commit=None) -> bool`
:   Delete by primary key and flush. `False` if no row has that key.

## Hooks to override

`_hydrate(self, model) -> DTO`
:   Convert a model instance to the DTO. Override when the automatic conversion
    cannot build your DTO. See [custom hydration](recipes/custom-methods.md#custom-hydration).

## Filter values

The values a `**filters` keyword understands beyond an ordinary match:

| Value   | Effect                    |
| ------- | ------------------------- |
| `None`  | filter by `IS NULL`       |
| `UNSET` | skip this filter entirely |

## `PaginatedResult`

```python
@dataclass(frozen=True, slots=True)
class PaginatedResult[DTO]:
    items: list[DTO]   # this page
    total: int         # all matching rows, ignoring offset/limit
```

## Design principles { #design-principles }

The four ideas that explain every choice in the API.

- **The session is the caller's.** repositron flushes and never closes the
  session, so transaction boundaries stay in your application code by default.
  Committing is opt-in, per instance (`autocommit=True`) or per write
  (`commit=True`); see [transactions](recipes/updates.md#transactions).
- **One source of truth per field name.** A rename declared once in
  `field_mapping` applies to both hydration and projection.
- **Ordering is never implicit.** `list` and `first` are unordered unless asked;
  `list_paginated` refuses to run without one. See [pagination](recipes/pagination.md#why-order_by-is-required).
- **`UNSET` is one canonical singleton,** compared by identity, shared across the
  whole library. There is no per-project variant to get subtly wrong.
