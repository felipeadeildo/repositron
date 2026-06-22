---
icon: lucide/key-round
---

# Primary keys

Not every table is keyed by an auto-incrementing `id`. repositron handles the
common variations, a different column name, a `str` or `uuid` key, without
ceremony, and types the id arguments along the way.

## The default: an integer `id`

Out of the box, a repository assumes the key column is named `id` and holds an
`int`. Every id-based method, `get`, `update`, `delete`, `exists`, is typed to
take an `int`, and `create` returns one:

??? note "Setup"

    The baseline is the task-tracker `Task` model and its repository. The
    key-type sections further down define their own models, since the page is
    about keys that are not this default.

    ```python
    from __future__ import annotations

    from dataclasses import dataclass

    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

    from repositron import ReadOnlyRepository, Repository, UNSET, UnsetType


    class Base(DeclarativeBase): ...


    class Task(Base):
        __tablename__ = "tasks"

        id: Mapped[int] = mapped_column(primary_key=True)
        workspace_id: Mapped[int]
        title: Mapped[str]
        status: Mapped[str] = mapped_column(default="open")


    @dataclass
    class TaskDTO:
        id: int
        title: str
        status: str


    @dataclass
    class TaskCreate:
        workspace_id: int
        title: str


    @dataclass
    class TaskUpdate:
        title: str | UnsetType = UNSET
        status: str | UnsetType = UNSET


    class TaskRepository(Repository[Task, TaskDTO, TaskCreate, TaskUpdate]): ...
    ```

```python
repo = TaskRepository(session)

repo.get(1)          # TaskDTO | None
repo.exists(1)       # bool
repo.get("1")        # type error: expected int, got str
```

That last line is the point: because the key type is part of the repository's
type, a checker (pyright, mypy, ty) catches a stringly-typed id before it runs.
For the 90% of tables keyed by an `int`, you get this for free, no extra
declaration.

## A key that is not an `int`

When the key is a `str`, a `uuid`, or anything else, declare its type as the
**last** type parameter. The slot is named `PKT` and it sits after the others so
the common case never has to mention it.

On a read-only repository it is the third parameter. A `Page` cache, keyed by
the hash of a fetched URL, is a natural `str` key:

```python
class Page(Base):
    __tablename__ = "pages"

    url_hash: Mapped[str] = mapped_column(primary_key=True)
    html: Mapped[str]


@dataclass
class PageDTO:
    url_hash: str
    html: str


class PageRepository(ReadOnlyRepository[Page, PageDTO, str]):
    pk_column = "url_hash"


repo.get("a1b2c3")   # PageDTO | None
repo.get(123)        # type error: expected str, got int
```

A `uuid` key on a full-CRUD repository is no different, name `uuid.UUID` as the
type. An API token keyed by a generated `token_id` is the typical case:

```python
import uuid


class ApiToken(Base):
    __tablename__ = "api_tokens"

    token_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[int]
    label: Mapped[str]


@dataclass
class ApiTokenDTO:
    token_id: uuid.UUID
    label: str


@dataclass
class ApiTokenCreate:
    workspace_id: int
    label: str


@dataclass
class ApiTokenUpdate:
    label: str | UnsetType = UNSET


class ApiTokenRepository(
    Repository[ApiToken, ApiTokenDTO, ApiTokenCreate, ApiTokenUpdate, uuid.UUID]
):
    pk_column = "token_id"


tid = repo.create(ApiTokenCreate(workspace_id=1, label="ci"))   # uuid.UUID
repo.get(tid)                                                   # ApiTokenDTO | None
```

!!! note "Why the type is declared and not inferred"

    You might expect `pk_column = Page.url_hash` to tell the checker the key
    is a `str` on its own. It cannot: Python has no way to read the type of a
    class attribute back into a generic parameter. The honest, checkable place to
    state it is the type parameter. The [typed primary keys](../design-notes/typed-keys.md)
    design note explains the machinery, and why `int` is the default.

### The slots are positional

Type parameters cannot be passed by name, so to reach `PKT` you fill the ones
before it. If a CRUD repository has real `Create`/`Update` payloads, declare
them, that is the honest signature anyway:

```python
Repository[ApiToken, ApiTokenDTO, ApiTokenCreate, ApiTokenUpdate, uuid.UUID]
```

Padding the payload slots with `object` only makes sense when you genuinely
don't use `create`/`update`. An append-only `AuditEntry` is written once and
never updated, so it has no update payload and the slot is padded:

```python
class AuditEntry(Base):
    __tablename__ = "audit_entries"

    trace_id: Mapped[str] = mapped_column(primary_key=True)
    action: Mapped[str]


@dataclass
class AuditEntryDTO:
    trace_id: str
    action: str


@dataclass
class AuditEntryCreate:
    trace_id: str
    action: str


# entries are created and read, never updated, so Update stays untyped
class AuditEntryRepository(
    Repository[AuditEntry, AuditEntryDTO, AuditEntryCreate, object, str]
):
    pk_column = "trace_id"
```

If you want typed creates and updates, declare them properly rather than reaching
for `object`.

## When the key is not called `id`

Independent of its type, point `pk_column` at the right column. Reusing the
`Page` cache from above, two forms work:

```python
class PageRepository(ReadOnlyRepository[Page, PageDTO, str]):
    pk_column = "url_hash"      # by name


class PageRepository(ReadOnlyRepository[Page, PageDTO, str]):
    pk_column = Page.url_hash   # by column reference
```

The string is terse; the column reference reads naturally next to the rest of
your SQLAlchemy code. Either way the column is resolved by name through the
model on first use, so a column from the wrong model (or a bad name) raises
`AttributeError` at the first query rather than cross-joining. Pick whichever you
prefer, they resolve to the same column. Both feed every id-based method:

```python
repo.get("a1b2c3")     # WHERE url_hash = 'a1b2c3'
repo.exists("a1b2c3")  # same column
```

This is the case for tables keyed by a natural identifier, a hash, a slug, an
external system's id, rather than a surrogate `id`.

## Filtering on the key like any other column

`pk_column` only affects the id-based methods. The key column is still an
ordinary attribute, so you can filter on it through the normal channels when you
want a query rather than a single fetch:

```python
repo.get("a1b2c3")     # one PageDTO | None, keyed lookup

hashes = ["a1b2c3", "d4e5f6", "789abc"]
repo.list(extra_filters=[Page.url_hash.in_(hashes)])   # list[PageDTO]
```

That returns a list, where `get` returns one. Reach for whichever matches what
you actually need.

## What about composite keys?

repositron's id-based methods assume a single key column. A table with a
composite primary key still works as a repository; you simply do not use `get` /
`update(id, ...)` / `delete(id)` against it. A `Membership` association keyed by
`(workspace_id, member_id)` is the classic shape. Filter on the key columns and
add your own methods for the lookups:

```python
from sqlalchemy import select


class Membership(Base):
    __tablename__ = "memberships"

    workspace_id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(default="member")


@dataclass
class MembershipDTO:
    workspace_id: int
    member_id: int
    role: str


class MembershipRepository(Repository[Membership, MembershipDTO]):

    def get(self, workspace_id: int, member_id: int) -> MembershipDTO | None:
        model = self.session.scalars(
            select(Membership)
            .where(Membership.workspace_id == workspace_id)
            .where(Membership.member_id == member_id)
        ).first()
        return self._hydrate(model) if model is not None else None
```

The read and filter machinery, `list`, `first`, `count`, `extra_filters`,
projection, is indifferent to how many columns make up the key.
