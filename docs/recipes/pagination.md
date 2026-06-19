---
icon: lucide/book-open
---

# Pagination

Pagination is the place where a small oversight turns into a bug that only shows
up in production, under load, for some users, some of the time. repositron is
opinionated here on purpose.

## A page and its total

`list_paginated` returns a `PaginatedResult`: the slice of rows for this page,
plus the total the query would return without the offset and limit. That total
is what you need to compute how many pages there are, so it comes back in the
same call rather than forcing a second one.

```python
page = repo.list_paginated(offset=0, limit=20, order_by=User.id)

page.items   # list[UserDTO]  -> this page
page.total   # int            -> all matching rows, ignoring offset/limit
```

It takes the same `extra_filters` and `**filters` as `list`, so filtering and
paginating compose exactly the way you would expect:

```python
page = repo.list_paginated(
    offset=offset,
    limit=limit,
    is_active=True,
    extra_filters=[User.created_at >= cutoff],
    order_by=User.created_at.desc(),
)
```

A typical service method wraps it and maps `total` into whatever your API's page
envelope looks like:

```python
def list_users(self, offset: int, limit: int, q: str | None = None):
    extra = [self.repo.search(q)] if q else None
    result = self.repo.list_paginated(
        offset=offset, limit=limit, extra_filters=extra, order_by=self.repo.ORDER
    )
    return Page(items=result.items, total=result.total, offset=offset, limit=limit)
```

## Why order_by is required

Here is the part that is not optional. `list_paginated` will raise a `ValueError`
if you do not give it an `order_by`:

```python
repo.list_paginated(0, 20)                     # ValueError
repo.list_paginated(0, 20, order_by=User.id)   # fine
```

This is deliberate. A database is free to return rows in any order when you do
not specify one, and that order can differ between two queries that are otherwise
identical. Page through such a result and rows silently shift across page
boundaries: some appear twice, some never appear at all. Nothing errors. The
counts even look right. You find out from a user asking where a record went.

repositron turns that quiet data bug into a loud error at the call site, the
moment you write the query, where it costs you ten seconds instead of a debugging
session. Pick a stable order, ideally one that ends in a unique column like the
primary key, and the problem cannot occur:

```python
repo.list_paginated(0, 20, order_by=[User.created_at.desc(), User.id])
```

## Pagination plays well with projection

Paginating a wide table while only showing a few columns is a natural pairing.
Project first, then paginate, and you fetch only what the page renders:

```python
page = repo[UserCard].list_paginated(0, 20, order_by=User.id)
# SELECT only UserCard's columns, paginated -> PaginatedResult[UserCard]
```

See the [projection recipe](projection.md) for what `repo[UserCard]` does.
