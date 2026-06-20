---
icon: lucide/rocket
---

# Get started

This page takes you from an empty file to a working, fully typed repository.
Read it once, start to finish. After that, the [recipes](recipes/index.md) cover
each capability in depth.

## Install

repositron runs on Python 3.13+ and SQLAlchemy 2.0.

=== "uv"

    ```bash
    uv add repositron
    ```

=== "pip"

    ```bash
    pip install repositron
    ```

SQLAlchemy is the only runtime dependency. If your return shapes are
dataclasses, that is the whole footprint. Nothing else comes along for the ride.

## A model to work with

Everything below builds on one ordinary SQLAlchemy model. There is nothing
repositron-specific in it, so if you already have models, point repositron at
those instead.

```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase): ...


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str]
    email: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
```

## Declare the shapes

A repository is described entirely by its type parameters. There are four, and
only the first is required:

```python
Repository[Model, DTO, Create, Update]
```

`Model` is your SQLAlchemy class. `DTO` is what reads hand back. `Create` and
`Update` are the dataclasses your writes accept. We will use all four so the
full picture is on the table, then come back later and learn how to drop the
ones you do not need.

```python
from dataclasses import dataclass
from repositron import Repository, UNSET, UnsetType


@dataclass(frozen=True, slots=True)
class UserDTO:                 # the shape reads return
    id: int
    name: str                  # the model column is called full_name
    email: str


@dataclass
class UserCreate:              # what create() accepts
    full_name: str
    email: str


@dataclass
class UserUpdate:              # what update() accepts
    full_name: str | UnsetType = UNSET
    email: str | UnsetType = UNSET
```

Notice that `UserDTO.name` does not match the model's `full_name` column. That
mismatch is intentional, and it is the one thing the repository cannot guess. So
you tell it once:

```python
class UserRepository(Repository[User, UserDTO, UserCreate, UserUpdate]):
    field_mapping = {"full_name": "name"}   # model column : DTO field
```

That is the entire class. Its body is a single attribute, and that attribute is
the only line you would have to change if the column were renamed tomorrow.
`field_mapping`, the type parameters, and the other knobs all get a proper
treatment in [Configuration](recipes/configuration.md).

## Use it

Hand the repository a session and every method is already there, already typed:

```python
repo = UserRepository(session)

repo.get(1)                                          # UserDTO | None
repo.list(is_active=True)                            # list[UserDTO]
repo.count(is_active=True)                           # int
repo.exists(1)                                       # bool
repo.create(UserCreate("Ada Lovelace", "ada@x.com")) # int  (the new id)
repo.update(1, UserUpdate(full_name="Ada L."))       # True; email untouched
repo.delete(1)                                       # bool
```

Hover any of those calls in your editor. `repo.list()` is `list[UserDTO]`, not
`list[Any]`. The same object you return here is the object your web framework
serializes, so there is no second schema to keep in step.

!!! note "The session stays yours"
    repositron never opens or closes the session, and by default writes only
    `flush`, leaving when to commit and roll back to your application. When you
    do want a write committed, opt in with `Repository(session, autocommit=True)`
    or per call with `repo.create(payload, commit=True)`; see
    [transactions](recipes/updates.md#transactions). One repository instance holds
    no per-call state, so it is safe to build once and inject everywhere. This
    boundary is one of the [design principles](reference.md#design-principles).

## Where to go next

You now have a working repository. The interesting parts are how it filters,
how it updates, and how it returns exactly the shape you ask for. Each has its
own recipe:

<div class="grid cards" markdown>

-   :material-tune:{ .lg .middle } __[Configuration](recipes/configuration.md)__

    ---

    How `field_mapping` works in both directions, the type-parameter defaults,
    `pk_column`, and the hooks you can override.

-   :material-filter-variant:{ .lg .middle } __[Filtering](recipes/filtering.md)__

    ---

    Equality by keyword and arbitrary SQLAlchemy expressions, combined in one
    call. Plus the two filter values that mean something special.

-   :material-null:{ .lg .middle } __[Updates & UNSET](recipes/updates.md)__

    ---

    The difference between "leave this alone" and "set this to NULL", and why the
    usual partial-update pattern cannot express it.

-   :material-book-open-page-variant:{ .lg .middle } __[Pagination](recipes/pagination.md)__

    ---

    A page plus its total, and why repositron refuses to paginate without an
    order.

-   :material-table-column:{ .lg .middle } __[Projection](recipes/projection.md)__

    ---

    Load only the columns a narrow shape needs, for one call, without touching
    the injected repository.

-   :material-shape:{ .lg .middle } __[Choosing a DTO](recipes/dtos.md)__

    ---

    Dataclass, the model itself, or a Pydantic schema you already have.
    repositron does the right thing for each.

-   :material-function-variant:{ .lg .middle } __[Custom methods](recipes/custom-methods.md)__

    ---

    The base gives you CRUD. Domain queries, batch inserts, and custom hydration
    are yours to add on top.

</div>
