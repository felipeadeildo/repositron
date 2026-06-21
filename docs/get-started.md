---
icon: lucide/rocket
---

# Get started

This page takes you from an empty file to a working, fully typed repository.
Read it once, start to finish. After that, the [guides](guides/index.md) cover
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
treatment in [Configuration](guides/configuration.md).

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
    [transactions](guides/updates.md#transactions). One repository instance holds
    no per-call state, so it is safe to build once and inject everywhere. This
    boundary is one of the [design principles](reference.md#design-principles).

## Where to go next

You now have a working repository. From here, the [Guides](guides/index.md) take
each capability one at a time, filtering, updating, pagination, projection,
return types, hooks, and the escape hatch for custom queries.
