---
icon: lucide/shapes
---

# Return types

The DTO is the shape your reads return. repositron supports three kinds, and the
right choice is usually obvious once you know what each costs. The rule of thumb:
use a dataclass unless you have a specific reason not to.

## Dataclass: the recommendation

A dataclass DTO is light, it is detached from the session, and it serializes to
JSON without ceremony. That last point is the quiet win: the object your
repository returns is the object your web framework sends, so there is no third
hand-written schema sitting between them, drifting out of sync.

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserDTO:
    id: int
    name: str
    email: str


class UserRepository(Repository[User, UserDTO]):
    field_mapping = {"full_name": "name"}
```

In a FastAPI route, the same type is the return annotation and the response
model:

```python
from typing import Annotated
from fastapi import Depends


@app.get("/users")
def list_users(repo: Annotated[UserRepository, Depends(get_repo)]) -> list[UserDTO]:
    return repo.list(order_by=User.created_at.desc())
```

`frozen=True, slots=True` is a good default: immutable, low-overhead, and a clear
signal that this is a value to read, not a row to mutate.

## Model as DTO: no hydration at all

Leave the DTO parameter off and the DTO defaults to the model itself. Reads then
return the model instances directly, with no conversion step:

```python
from repositron import Repository


class AccountRepository(Repository[Account]):   # DTO defaults to Account
    pass


repo.get(1)                  # Account | None
repo.list(status="active")   # list[Account]
```

This is the lightest path in CPU terms, since nothing is copied. The trade-off is
that what you hand back is attached to the session and is a full ORM object, so
it is best when the caller is internal and lives inside the same transaction, not
when you are about to serialize it across an HTTP boundary.

## Pydantic: reuse a schema you already have

If your project already defines a Pydantic response model, that model *is* a
valid DTO. repositron detects Pydantic and hydrates through `model_validate`, so
you do not declare the shape twice:

```python
from pydantic import BaseModel, ConfigDict


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class UserRepository(Repository[User, UserOut]): ...

repo.list()   # list[UserOut], ready to return over HTTP
```

The `from_attributes=True` config is what lets Pydantic read straight off the
model. Pydantic stays a genuinely optional dependency: repositron duck-types on
`model_validate` rather than importing Pydantic, so the dataclass path never pulls
it in.

## Picking, in one line each

| If you want to...                                   | Use            |
| --------------------------------------------------- | -------------- |
| return light objects over HTTP, one source of truth | dataclass      |
| work with full ORM rows inside a transaction        | model as DTO   |
| reuse an existing Pydantic response schema          | Pydantic       |

When a DTO needs a value the row alone cannot give, for instance data from
another table, add it with a [`hydrate` hook](hooks.md#enriching-the-dto). The
rarer case, a DTO the automatic build cannot produce at all, is an `_hydrate`
override, covered in [custom methods](custom-queries.md#custom-hydration).
