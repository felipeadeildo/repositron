---
icon: lucide/key-round
---

# Primary keys

Not every table is keyed by an auto-incrementing `id`. repositron handles the
common variations without ceremony.

## Any of int, str, or uuid

A primary key value is a `PrimaryKey`, which is `int | str | uuid.UUID`. Every
method that takes an id, `get`, `update`, `delete`, `exists`, accepts any of the
three. You do not configure the type; it follows from your model.

```python
import uuid

repo.get(1)                 # int key
repo.get("user_abc123")     # str key
repo.get(uuid.uuid4())      # uuid key
```

A `uuid` key works exactly like an `int` one, all the way through reads and
writes:

```python
class AccountRepository(Repository[Account, AccountDTO]):
    pass

acc = repo.get(uuid.uuid4())          # AccountDTO | None
repo.delete(uuid.UUID(some_string))   # bool
```

## When the key is not called id

The base class assumes the primary-key column is named `id`. When it is named
something else, set `pk_column` on the repository:

```python
class PageRepository(Repository[Page, PageDTO]):
    pk_column = "url_hash"   # the primary key column, not "id"
```

That single attribute is all that `get`, `update`, `delete`, `exists`, and the
internal count query need. They all resolve the key through `pk_column`:

```python
repo.get("a1b2c3...")     # WHERE url_hash = 'a1b2c3...'
repo.exists("a1b2c3...")  # same column
```

This is the common case for tables keyed by a natural identifier, a hash, a slug,
an external system's id, rather than a surrogate `id`.

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
