---
icon: lucide/sliders-horizontal
---

# Configuration

A repository is configured in three places: the **type parameters** it inherits
with, the **class attributes** it sets, and the **hooks** it declares with `@on`.
This page is the full map of what you can change and how each piece behaves. Most
repositories touch only the first two.

## The one idea: convention first, configuration only when you diverge

Here is the mental model that makes the rest of this page obvious.

By default, **repositron expects your DTO to mirror your model**: the same field
names, the same types. When that holds, nothing needs configuring. You declare
the DTO, inherit the repository, and hydration just works, field by matching
field.

```python
class User(Base):
    id: Mapped[int]
    name: Mapped[str]
    email: Mapped[str]


@dataclass(frozen=True, slots=True)
class UserDTO:        # same names, same types as the columns
    id: int
    name: str
    email: str


class UserRepository(Repository[User, UserDTO]):
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

That is why all of these are valid, each adding only what it uses:

```python
class AccountRepository(Repository[Account]): ...
# read/write, returns Account, int key, no separate DTO or payloads declared

class UserReadRepo(ReadOnlyRepository[User, UserDTO]): ...
# read-only, returns UserDTO, int key

class UserRepo(Repository[User, UserDTO, UserCreate, UserUpdate]): ...
# the full set, int key

class SessionRepo(Repository[Session, SessionDTO, SessionCreate, SessionUpdate, str]): ...
# full set with a string key
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
the column is `full_name`, but your DTO (and your API) calls it `name`.
`field_mapping` records that rename once.

The direction is **`{model_column: dto_field}`**, read as "the model's
`full_name` is the DTO's `name`":

```python
class UserRepository(Repository[User, UserDTO]):
    field_mapping = {"full_name": "name"}
```

```python
class User(Base):
    full_name: Mapped[str]    # the column

@dataclass
class UserDTO:
    name: str                 # the field
```

### It applies in both directions

This is the part worth internalizing: one mapping covers every direction data
flows through the repository.

- **Reading (hydration).** When a row becomes a `UserDTO`, the column `full_name`
  is read into the field `name`.
- **Projecting.** When you do `repo[UserCard].list()` and `UserCard` has a `name`
  field, repositron resolves it back to the `full_name` column to build the
  `SELECT`. See [projection](projection.md).
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
class PageRepository(Repository[Page, PageDTO, ..., ..., str]):
    pk_column = "url_hash"        # by name

class PageRepository(Repository[Page, PageDTO, ..., ..., str]):
    pk_column = Page.url_hash     # by column reference (checked against the model)
```

The column's *name* is a runtime concern (`pk_column`); the key's *type* is the
last type parameter (`PK`). They are separate knobs. The details, including
`str`/`uuid` keys and composite keys, live in [primary keys](primary-keys.md).

## Defaults you can override at the class level

Beyond the two configured attributes, a common convention is to attach a
canonical ordering to the repository so callers do not repeat it:

```python
class UserRepository(Repository[User, UserDTO]):
    field_mapping = {"full_name": "name"}
    ORDER = User.created_at.desc()

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
class UserRepository(Repository[User, UserProfile]):
    @on("hydrate", mode="after")
    def with_roles(self, model: User, dto: UserProfile) -> UserProfile:
        return replace(dto, roles=self._load_roles(model.id))
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
