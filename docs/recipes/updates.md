---
icon: lucide/pencil
---

# Updates & UNSET

This is the feature people do not notice until the day it would have saved them.

## The blind spot in the usual pattern

Almost every hand-written partial update looks like this:

```python
if full_name is not None:
    user.full_name = full_name
if email is not None:
    user.email = email
```

It reads fine, and it is wrong in one specific way: it cannot set a column to
`NULL`. "The caller did not mention this field" and "the caller wants this field
cleared" both arrive as `None`, and the `is not None` guard collapses them into
the same branch. To null a column on purpose you have to invent a second
convention, and now your update path has two ways to say "change nothing".

## Two sentinels, two meanings

repositron keeps the two intents apart with a dedicated sentinel:

| You pass        | Meaning                 | Result            |
| --------------- | ----------------------- | ----------------- |
| `UNSET`         | leave this column alone | column unchanged  |
| `None`          | set this column to NULL | `column = NULL`   |
| any other value | set it                  | `column = value`  |

You opt in by defaulting your update fields to `UNSET`:

```python
from dataclasses import dataclass
from repositron import UNSET, UnsetType


@dataclass
class UserUpdate:
    full_name: str | UnsetType = UNSET
    email: str | None | UnsetType = UNSET   # None is a real, allowed value here
```

Now the three outcomes are all expressible, and they read exactly as they mean:

```python
repo.update(1, UserUpdate(full_name="Ada"))   # email untouched
repo.update(1, UserUpdate(email=None))          # email becomes NULL
repo.update(1, UserUpdate())                    # a no-op write
```

Under the hood, `update` walks the payload's fields, skips any that are still
`UNSET`, and writes the rest, `None` included. A field left at its `UNSET`
default never appears in the `UPDATE` statement at all.

## UNSET on create, too

The same sentinel is useful on the create side, for a different reason. A field
left `UNSET` is simply omitted from the insert, which lets the column's database
default (or the model's) take over instead of you hard-coding it in the payload:

```python
@dataclass
class UserCreate:
    name: str
    email: str
    role: str | UnsetType = UNSET   # omit it -> the column default applies


repo.create(UserCreate(name="Ada", email="ada@x.com"))   # role uses its default
repo.create(UserCreate(name="Grace", email="g@x.com", role="admin"))
```

This is handy at the boundary between an HTTP layer and the repository: an
optional request field that was not provided maps cleanly to `UNSET`, and the
database fills in what it always would have.

```python
payload = UserCreate(
    name=name,
    email=email,
    role=role if role is not None else UNSET,
)
```

## Return value

`update` returns `True` on success and `False` when no row has that primary key,
so a missing record is an ordinary boolean to handle, not an exception to catch:

```python
if not repo.update(user_id, UserUpdate(email=new_email)):
    raise NotFound(user_id)
```

`delete` follows the same convention. `create` returns the new primary key.
