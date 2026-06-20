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

```python
class UserRepository(Repository[User, UserDTO, UserCreate, UserUpdate]):
    pass


repo.get(1)          # UserDTO | None
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

On a read-only repository it is the third parameter:

```python
class AccountRepository(ReadOnlyRepository[Account, AccountDTO, str]):
    pk_column = "account_id"


repo.get("acct_123")   # AccountDTO | None
repo.get(123)          # type error: expected str, got int
```

On a full-CRUD `Repository` it is the fifth, after `Create` and `Update`:

```python
class SessionRepository(
    Repository[Session, SessionDTO, SessionCreate, SessionUpdate, str]
):
    pk_column = "url_hash"


sid = repo.create(SessionCreate(...))   # str
repo.delete("abc-def")                  # bool
```

A `uuid` key is no different, name `uuid.UUID` as the type:

```python
class TokenRepository(Repository[Token, TokenDTO, TokenCreate, TokenUpdate, uuid.UUID]):
    pk_column = "token_id"


repo.get(uuid.uuid4())   # TokenDTO | None
```

!!! note "Why the type is declared and not inferred"

    You might expect `pk_column = Account.account_id` to tell the checker the key
    is a `str` on its own. It cannot: Python has no way to read the type of a
    class attribute back into a generic parameter. The honest, checkable place to
    state it is the type parameter. The [limitations](../limitations.md) page
    explains the machinery, and why `int` is the default.

### The slots are positional

Type parameters cannot be passed by name, so to reach `PKT` you fill the ones
before it. If a CRUD repository has real `Create`/`Update` payloads, declare
them, that is the honest signature anyway:

```python
Repository[Session, SessionDTO, SessionCreate, SessionUpdate, str]
```

Padding the payload slots with `object` only makes sense when you genuinely
don't use `create`/`update`, for example a repository you keep only for
`delete`:

```python
# only delete() is ever called, so Create/Update stay untyped
class PurgeRepository(Repository[Audit, Audit, object, object, str]):
    pk_column = "trace_id"
```

If you want typed creates and updates, declare them properly rather than reaching
for `object`.

## When the key is not called `id`

Independent of its type, point `pk_column` at the right column. Two forms work:

```python
class PageRepository(Repository[Page, PageDTO, ..., ..., str]):
    pk_column = "url_hash"      # by name


class PageRepository(Repository[Page, PageDTO, ..., ..., str]):
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
repo.list(extra_filters=[Page.url_hash.in_(hashes)])
```

That returns a list, where `get` returns one. Reach for whichever matches what
you actually need.

## What about composite keys?

repositron's id-based methods assume a single key column. A table with a
composite primary key still works as a repository; you simply do not use `get` /
`update(id, ...)` / `delete(id)` against it. Filter on the key columns and add
your own methods for the writes:

```python
class MembershipRepository(Repository[Membership, MembershipDTO]):
    def get(self, user_id: int, org_id: int) -> MembershipDTO | None:
        return self.first(user_id=user_id, organization_id=org_id)
```

The read and filter machinery, `list`, `first`, `count`, `extra_filters`,
projection, is indifferent to how many columns make up the key.
