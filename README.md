# repositron

A typed, generic repository base for SQLAlchemy 2.0. Declare a model (and
optionally a DTO and write payloads), inherit one generic class, and get
`get` / `first` / `list` / `list_paginated` / `count` / `exists` / `create` /
`update` / `delete` with no per-table boilerplate.

Every method is fully typed off the generic parameters, so your editor knows
that `repo.list()` returns `list[TargetDTO]` and `repo.get(id)` takes an `int`
(or a `uuid.UUID`, your choice).

```python
class TargetRepository(Repository[Target, TargetDTO, TargetCreate, TargetUpdate]):
    field_mapping = {"mention_rank": "rank"}

repo.list(is_active=True, order_by=Target.created_at.desc())  # -> list[TargetDTO]
repo.update(1, TargetUpdate(name="Ale"))                      # only name; rank untouched
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
class TargetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, id: int) -> TargetDTO | None:
        row = self.session.query(Target).filter(Target.id == id).first()
        if row is None:
            return None
        return TargetDTO(id=row.id, name=row.name, rank=row.mention_rank)

    def list(self, *, is_active: bool | None = None) -> list[TargetDTO]:
        query = self.session.query(Target)
        if is_active is not None:
            query = query.filter(Target.is_active == is_active)
        return [
            TargetDTO(id=r.id, name=r.name, rank=r.mention_rank)
            for r in query.order_by(Target.created_at.desc()).all()
        ]

    def list_paginated(self, offset: int, limit: int = 20) -> tuple[list[TargetDTO], int]:
        query = self.session.query(Target).order_by(Target.created_at.desc())
        total = query.order_by(None).count()
        rows = query.offset(offset).limit(limit).all()
        return [TargetDTO(id=r.id, name=r.name, rank=r.mention_rank) for r in rows], total

    def count(self, *, is_active: bool | None = None) -> int:
        query = self.session.query(Target.id)
        if is_active is not None:
            query = query.filter(Target.is_active == is_active)
        return query.count()

    def create(self, name: str, mention_rank: int) -> int:
        target = Target(name=name, mention_rank=mention_rank)
        self.session.add(target)
        self.session.flush()
        return target.id

    def update(self, id: int, *, name: str | None = None, mention_rank: int | None = None) -> bool:
        target = self.session.query(Target).filter(Target.id == id).first()
        if target is None:
            return False
        if name is not None:          # but how do you set a column to NULL on purpose?
            target.name = name
        if mention_rank is not None:
            target.mention_rank = mention_rank
        self.session.flush()
        return True

    # ...and delete, and first, and the same again for the next ten tables.
```

### After: declare it once

```python
from dataclasses import dataclass
from repositron import Repository, UNSET, UnsetType


@dataclass(frozen=True, slots=True)
class TargetDTO:               # light, detached, serializes straight to JSON
    id: int
    name: str
    rank: int                  # renamed from the model column `mention_rank`


@dataclass
class TargetCreate:
    name: str
    mention_rank: int


@dataclass
class TargetUpdate:
    name: str | UnsetType = UNSET          # absent = leave alone; None = SET NULL
    mention_rank: int | UnsetType = UNSET


class TargetRepository(Repository[Target, TargetDTO, TargetCreate, TargetUpdate]):
    field_mapping = {"mention_rank": "rank"}
```

That is the whole repository. Every method above comes for free, typed against
`TargetDTO`:

```python
repo = TargetRepository(session)

repo.get(1)                                          # -> TargetDTO | None
repo.list(is_active=True, order_by=Target.created_at.desc())
repo.list_paginated(0, 20, order_by=Target.created_at.desc())  # -> PaginatedResult[TargetDTO]
repo.count(is_active=True)
repo.create(TargetCreate(name="Ale", mention_rank=3))          # -> int (new id)
repo.update(1, TargetUpdate(name="Ale"))                       # rank left untouched
repo.delete(1)
```

## The sugar

### Two ways to filter, in one call

Equality is keyed by attribute name. Anything else is a plain SQLAlchemy
expression. They combine.

```python
repo.list(
    name="Ale",                          # equality
    extra_filters=[Target.age > 18],     # any expression: >, IN, LIKE, OR, ...
    order_by=[Target.created_at.desc(), Target.id],
)
# WHERE name = 'Ale' AND age > 18 ORDER BY created_at DESC, id
```

A filter value of `None` means `IS NULL`; `UNSET` skips the filter entirely, so
you can pass through optional query params without branching.

### Partial updates that can actually write NULL

`UNSET` and `None` are different on purpose. `UNSET` says "don't touch this
column"; `None` says "set it to NULL". The hand-written `if x is not None`
pattern can't express the second one.

```python
repo.update(1, TargetUpdate(name="Ale"))         # rank stays whatever it was
repo.update(1, TargetUpdate(mention_rank=None))  # rank IS NULL now
```

### Column projection: load only what you need

Index the repo with a narrow DTO and it selects only those columns, returning
that shape, for the duration of the call. The injected repository is untouched.

```python
@dataclass(frozen=True, slots=True)
class TargetIdOrg:
    id: int
    organization_id: int

repo[TargetIdOrg].list(is_active=True)   # SELECT id, organization_id -> list[TargetIdOrg]
repo[TargetIdOrg].first(id=5)
```

### Pagination is ordered, or it raises

Pagination over an unstable order silently drops and repeats rows across pages,
so `list_paginated` requires `order_by`. Forgetting it is a `ValueError`, not a
heisenbug in production.

```python
repo.list_paginated(0, 20)                                 # ValueError
repo.list_paginated(0, 20, order_by=Target.id)             # PaginatedResult(items=[...], total=...)
```

## Three shapes of DTO

The DTO is an optimization, not a mandate. Pick the one that fits, and pay only
for what you use.

### 1. Dataclass DTO (the recommendation)

Lightest, detached from the session, and FastAPI serializes it natively, so the
same object is your repository return value and your `response_model`. No third
hand-written schema.

```python
@app.get("/targets", response_model=list[TargetDTO])
def list_targets(repo: TargetRepository = Depends(get_repo)):
    return repo.list(order_by=Target.created_at.desc())
```

### 2. No DTO at all (model as DTO)

Leave the DTO parameter off and the repository returns the model itself. No
hydration, no dict round-trip. Set the id type when your keys aren't `int`:

```python
import uuid
from repositron import Repository

class SiteRepository(Repository[Site, Site, SiteCreate, SiteUpdate, uuid.UUID]):
    pass

repo.get(uuid.uuid4())        # -> Site | None, typed on UUID
repo.list(status="active")    # -> list[Site]
```

### 3. Pydantic DTO

If you already have a Pydantic response schema, it is the DTO. repositron
detects Pydantic and hydrates through `model_validate`.

```python
class TargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str

class TargetRepository(Repository[Target, TargetOut]): ...
repo.list()   # -> list[TargetOut], ready for HTTP
```

## Public API

```python
from repositron import (
    Repository,            # full CRUD generic base
    ReadOnlyRepository,    # read-only generic base
    PaginatedResult,       # {items, total} container
    UNSET, UnsetType,      # partial-update sentinel
)
```

Type parameters: `Repository[ModelT, DTOT=ModelT, CreateT, UpdateT, IdT=int]`.
`ModelT` is required; everything else has a default, so
`Repository[Site]` is a valid read/write repository returning `Site` on `int`
keys.

| Class attribute | Purpose | Default |
|---|---|---|
| `field_mapping` | `{model_field: dto_field}` for renamed fields | `{}` |
| `pk_column` | primary-key column name | `"id"` |

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
