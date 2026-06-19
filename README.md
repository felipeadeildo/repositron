<h1 align="center">repositron</h1>

<p align="center">
    <em>A typed, generic repository base for SQLAlchemy 2.0. Full CRUD, zero per-table boilerplate.</em>
</p>

<p align="center">
<a href="https://github.com/felipeadeildo/repositron/actions/workflows/release.yml">
    <img src="https://github.com/felipeadeildo/repositron/actions/workflows/release.yml/badge.svg" alt="Release">
</a>
<a href="https://pypi.org/project/repositron">
    <img src="https://img.shields.io/pypi/v/repositron?color=%2334D058&label=pypi" alt="Package version">
</a>
<a href="https://pypi.org/project/repositron">
    <img src="https://img.shields.io/pypi/pyversions/repositron.svg?color=%2334D058" alt="Supported Python versions">
</a>
<a href="https://github.com/felipeadeildo/repositron/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License">
</a>
</p>

---

**Documentation**: [https://repositron.fa.dev.br](https://repositron.fa.dev.br)

**Source Code**: [https://github.com/felipeadeildo/repositron](https://github.com/felipeadeildo/repositron)

---

Declare a model (and optionally a DTO and write payloads), inherit one generic
class, and get `get` / `first` / `list` / `list_paginated` / `count` / `exists`
/ `create` / `update` / `delete` with no per-table boilerplate.

Every method is fully typed off the generic parameters, so your editor knows
that `repo.list()` returns `list[UserDTO]`. Primary keys can be `int`, `str`, or
`uuid.UUID` — `repo.get(id)` takes any of them.

```python
class UserRepository(Repository[User, UserDTO, UserCreate, UserUpdate]):
    field_mapping = {"full_name": "name"}

repo.list(is_active=True, order_by=User.created_at.desc())  # -> list[UserDTO]
repo.update(1, UserUpdate(name="Ada"))                      # only name; others untouched
```

## Install

```bash
uv add repositron        # or: pip install repositron
```

Requires Python 3.13+ and `sqlalchemy>=2.0`. That is the only dependency; the
dataclass path pulls in nothing else.

## The before / after

Every SQLAlchemy project rewrites the same layer: a class per table wrapping
`session.query(...)`, the same `get` / `list` / `count`, the same pagination
math, the same "turn the ORM row into something light to return". It is
mechanical and easy to get subtly wrong.

### Before: hand-written, per table

```python
class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, id: int) -> UserDTO | None:
        row = self.session.query(User).filter(User.id == id).first()
        if row is None:
            return None
        return UserDTO(id=row.id, name=row.full_name, email=row.email)

    def list(self, *, is_active: bool | None = None) -> list[UserDTO]:
        query = self.session.query(User)
        if is_active is not None:
            query = query.filter(User.is_active == is_active)
        return [
            UserDTO(id=r.id, name=r.full_name, email=r.email)
            for r in query.order_by(User.created_at.desc()).all()
        ]

    def list_paginated(self, offset: int, limit: int = 20) -> tuple[list[UserDTO], int]:
        query = self.session.query(User).order_by(User.created_at.desc())
        total = query.order_by(None).count()
        rows = query.offset(offset).limit(limit).all()
        return [UserDTO(id=r.id, name=r.full_name, email=r.email) for r in rows], total

    def count(self, *, is_active: bool | None = None) -> int:
        query = self.session.query(User.id)
        if is_active is not None:
            query = query.filter(User.is_active == is_active)
        return query.count()

    def create(self, full_name: str, email: str) -> int:
        user = User(full_name=full_name, email=email)
        self.session.add(user)
        self.session.flush()
        return user.id

    def update(self, id: int, *, full_name: str | None = None, email: str | None = None) -> bool:
        user = self.session.query(User).filter(User.id == id).first()
        if user is None:
            return False
        if full_name is not None:     # but how do you set a column to NULL on purpose?
            user.full_name = full_name
        if email is not None:
            user.email = email
        self.session.flush()
        return True

    # ...and delete, and first, and the same again for the next ten tables.
```

### After: declare it once

```python
from dataclasses import dataclass
from repositron import Repository, UNSET, UnsetType


@dataclass(frozen=True, slots=True)
class UserDTO:                 # light, detached, serializes straight to JSON
    id: int
    name: str                  # renamed from the model column `full_name`
    email: str


@dataclass
class UserCreate:
    full_name: str
    email: str


@dataclass
class UserUpdate:
    full_name: str | UnsetType = UNSET     # absent = leave alone; None = SET NULL
    email: str | UnsetType = UNSET


class UserRepository(Repository[User, UserDTO, UserCreate, UserUpdate]):
    field_mapping = {"full_name": "name"}
```

That is the whole repository. Every method above comes for free, typed against
`UserDTO`:

```python
repo = UserRepository(session)

repo.get(1)                                          # -> UserDTO | None
repo.list(is_active=True, order_by=User.created_at.desc())
repo.list_paginated(0, 20, order_by=User.created_at.desc())  # -> PaginatedResult[UserDTO]
repo.count(is_active=True)
repo.create(UserCreate(full_name="Ada Lovelace", email="ada@example.com"))  # -> int (new id)
repo.update(1, UserUpdate(full_name="Ada L."))       # email left untouched
repo.delete(1)
```

## The sugar

### Two ways to filter, in one call

Equality is keyed by attribute name. Anything else is a plain SQLAlchemy
expression. They combine.

```python
repo.list(
    is_active=True,                      # equality
    extra_filters=[User.age > 18],       # any expression: >, IN, LIKE, OR, ...
    order_by=[User.created_at.desc(), User.id],
)
# WHERE is_active = true AND age > 18 ORDER BY created_at DESC, id
```

A filter value of `None` means `IS NULL`; `UNSET` skips the filter entirely, so
you can pass through optional query params without branching.

### Partial updates that can actually write NULL

`UNSET` and `None` are different on purpose. `UNSET` says "don't touch this
column"; `None` says "set it to NULL". The hand-written `if x is not None`
pattern can't express the second one.

```python
repo.update(1, UserUpdate(full_name="Ada"))     # email stays whatever it was
repo.update(1, UserUpdate(email=None))          # email IS NULL now
```

### Column projection: load only what you need

Index the repo with a narrow DTO and it selects only those columns, returning
that shape, for the duration of the call. The injected repository is untouched.

```python
@dataclass(frozen=True, slots=True)
class UserIdEmail:
    id: int
    email: str

repo[UserIdEmail].list(is_active=True)   # SELECT id, email -> list[UserIdEmail]
repo[UserIdEmail].first(id=5)
```

### Pagination is ordered, or it raises

Pagination over an unstable order silently drops and repeats rows across pages,
so `list_paginated` requires `order_by`. Forgetting it is a `ValueError`, not a
heisenbug in production.

```python
repo.list_paginated(0, 20)                                 # ValueError
repo.list_paginated(0, 20, order_by=User.id)               # PaginatedResult(items=[...], total=...)
```

## Three shapes of DTO

The DTO is an optimization, not a mandate. Pick the one that fits, and pay only
for what you use.

### 1. Dataclass DTO (the recommendation)

Lightest, detached from the session, and FastAPI serializes it natively, so the
same object is your repository return value and your `response_model`. No third
hand-written schema.

```python
@app.get("/users")
def list_users(repo: Annotated[UserRepository, Depends(get_repo)]) -> list[UserDTO]:
    return repo.list(order_by=User.created_at.desc())
```

### 2. No DTO at all (model as DTO)

Leave the DTO parameter off and the repository returns the model itself. No
hydration, no dict round-trip. Works the same whatever the key type — here the
table is keyed by `uuid.UUID`:

```python
import uuid
from repositron import Repository

class AccountRepository(Repository[Account, Account, AccountCreate, AccountUpdate]):
    pass

repo.get(uuid.uuid4())        # -> Account | None
repo.list(status="active")    # -> list[Account]
```

### 3. Pydantic DTO

If you already have a Pydantic response schema, it is the DTO. repositron
detects Pydantic and hydrates through `model_validate`.

```python
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str

class UserRepository(Repository[User, UserOut]): ...
repo.list()   # -> list[UserOut], ready for HTTP
```

## Public API

```python
from repositron import (
    Repository,            # full CRUD generic base
    ReadOnlyRepository,    # read-only generic base
    PaginatedResult,       # {items, total} container
    PrimaryKey,            # primary-key value type: int | str | uuid.UUID
    OrderBy,               # order_by argument type
    UNSET, UnsetType,      # partial-update sentinel
)
```

Type parameters: `Repository[ModelT, DTOT=ModelT, CreateT, UpdateT]`.
`ModelT` is required; everything else has a default, so `Repository[Account]`
is a valid read/write repository returning `Account`. Primary keys are
`PrimaryKey` (`int | str | uuid.UUID`).

| Class attribute | Purpose                                       | Default |
| --------------- | --------------------------------------------- | ------- |
| `field_mapping` | `{model_field: dto_field}` for renamed fields | `{}`    |
| `pk_column`     | primary-key column name                       | `"id"`  |

## Design notes

- The session is the caller's. The repository never opens, commits, or closes
  it; writes `flush`, so transaction boundaries stay in the app.
- One source of truth per field name: declare a rename once in `field_mapping`
  and it applies to both hydration and projection.
- Ordering is never implicit. `list` / `first` default to unordered; pagination
  refuses to run without an order.
- `UNSET` is one canonical singleton, compared by identity. There is no
  per-project override.

## License

MIT. See [LICENSE](LICENSE).
