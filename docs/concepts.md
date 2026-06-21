---
icon: lucide/book-open
---

# Concepts

repositron leans on a handful of words, in its API and across these docs. None of
them are invented here, they are the everyday vocabulary of data access in
Python, but it is worth pinning down what each means so the rest reads cleanly.

## The repository pattern

A **repository** is the one object that knows how to read and write a given kind
of record. Instead of scattering `session.query(User)...` across your routes,
services, and scripts, you put that logic behind a `UserRepository` and call
`repo.get(1)` or `repo.list(is_active=True)`. The rest of your code asks for what
it wants and never touches the database directly.

The point is a seam. On one side, your application speaks in domain terms
(`repo.create(...)`, `repo.list(...)`); on the other, the repository speaks SQL.
You can read the calling code without reading SQL, swap the storage details
without touching callers, and test against a fake repository. That is the
**repository pattern**, an old idea, and a good one.

The catch is that hand-writing one repository class per table is tedious and
repetitive: the same `get` / `list` / `count`, the same pagination math, the same
row-to-object mapping, table after table. repositron is a generic, typed base
that gives you all of that from a single declaration, so you write a repository
without writing the boilerplate. The rest of this page is the vocabulary that
base uses.

## Model

The **model** is your SQLAlchemy mapped class, the `User`, `Article`, or `Order`
with `Mapped[...]` columns that maps to a table. It is the source of truth for
the schema, and repositron reads everything it needs (columns, the primary key)
off it. You already have models; repositron does not replace them.

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str | None]
```

## DTO

A **DTO** (data transfer object) is the shape a repository *returns*. A model
instance is tied to the session, lazy-loads, and carries the whole row; often you
want something lighter to hand to an HTTP layer or another part of the app: a
plain object with exactly the fields you need, detached from the database.

In repositron the DTO is a type parameter. Point it at a dataclass and reads come
back as that dataclass; leave it off and reads return the model itself. Either
way, your editor knows the return type.

```python
@dataclass(frozen=True, slots=True)
class UserDTO:
    id: int
    name: str
```

The DTO is an optimization, not a requirement, [choosing a
return type](guides/return-types.md) covers when each kind pays off.

## Hydration

**Hydration** is turning a model row into a DTO, copying the columns across,
honoring any renames, building the DTO instance. repositron does this for you on
every read: a dataclass DTO is built field by field, a Pydantic DTO goes through
`model_validate`, and a model-as-DTO is returned untouched.

When a DTO needs a value no column holds (a count, a join, a derived field), you
add it with a [`hydrate` hook](guides/hooks.md#enriching-the-dto), repositron
hydrates the columns, your hook fills the rest. When the DTO is something the
automatic build can't produce at all, like a plain `str`, you replace the build
itself with a [`build` hook](guides/hooks.md#replacing-the-build).

## Payload

A **payload** is the shape a repository *accepts* on a write. Reads return a DTO;
writes take a payload, a `UserCreate` for `create`, a `UserUpdate` for `update`.
Keeping them separate from the DTO means a create can require different fields
than a read returns, and an update can express "leave this field alone" as
distinct from "set it to NULL" (see [updating rows](guides/updates.md)).

```python
@dataclass
class UserCreate:
    name: str
    email: str | None = None
```

## Primary key

The **primary key** (PK) is the column that identifies one row, what `get`,
`update`, and `delete` take, and what `create` returns. It is `id` and an `int`
by default. When yours differs, you declare two separate things: its *type* (the
last type parameter, e.g. `str` or `uuid.UUID`) and, if the column is not named
`id`, its *name* (the `pk_column` attribute). [Primary
keys](guides/primary-keys.md) covers why those are two knobs and not one.

## Projection

**Projection** is reading only some columns instead of the whole row. A list
endpoint that shows a name and an avatar does not need the bio, the settings
blob, and the timestamps. With `repo[Shape]`, repositron selects only the columns
that narrow `Shape` declares and returns that shape, for that one call, the
database ships less and you get back exactly what you asked for. See [projecting
columns](guides/projection.md).

```python
repo[UserCard].list()   # SELECT id, name  ->  list[UserCard]
```

---

With the vocabulary in hand, [Get started](get-started.md) puts it together into
a working repository in a few lines.
