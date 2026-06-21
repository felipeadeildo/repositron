---
icon: lucide/filter
---

# Filtering

Most queries are a `WHERE` clause and an `ORDER BY`. repositron gives you two
ways to write the `WHERE`, and they live in the same call, so you never have to
choose between the readable one and the powerful one.

## Equality reads as keyword arguments

The common case is matching a column to a value. Pass it as a keyword argument,
keyed by the model's attribute name:

```python
repo.list(is_active=True)
repo.list(is_active=True, organization_id=42)
```

Each keyword becomes a `column == value` and they join with `AND`. If you name a
keyword that is not an attribute on the model, that is a `ValueError` at the call
site, not a silent empty result.

## Everything else is a SQLAlchemy expression

Equality covers a lot, but not comparisons, `IN`, `LIKE`, or `OR`. For those,
hand repositron the real SQLAlchemy expressions through `extra_filters`. It is a
list, and every entry is `AND`-ed in alongside the keyword filters:

```python
repo.list(
    is_active=True,
    extra_filters=[
        User.created_at >= cutoff,
        User.email.like("%@work.com"),
    ],
)
# WHERE is_active = true
#   AND created_at >= :cutoff
#   AND email LIKE '%@work.com'
```

Because `extra_filters` is just SQLAlchemy, anything the ORM can express fits,
including `OR` and `IN` over a list you built at runtime:

```python
from sqlalchemy import or_

repo.list(extra_filters=[User.id.in_(wanted_ids)])

repo.list(extra_filters=[or_(User.name.ilike(q), User.email.ilike(q))])
```

That last pattern, a free-text search across a couple of columns, is common
enough that it is worth wrapping in a method on your repository so callers do not
repeat it. See [custom methods](custom-queries.md#filter-builders) for that.

## The two special filter values

A keyword filter understands two values beyond the obvious:

| You pass | Meaning |
| -------- | ------- |
| `None`   | filter by `IS NULL` |
| `UNSET`  | skip this filter entirely |

`None` filtering by `IS NULL` is what you would hope for:

```python
repo.list(deprecated_at=None)   # WHERE deprecated_at IS NULL
```

`UNSET` is the quietly useful one. It means "pretend I did not pass this filter
at all", which removes the branching from any endpoint that forwards optional
query parameters:

```python
from repositron import UNSET, UnsetType

def list_users(
    organization_id: int | None = None,
    is_active: bool | UnsetType = UNSET,
):
    # is_active defaults to UNSET, so no filter is applied unless the caller set it.
    # organization_id=None would filter by IS NULL, which is a different intent,
    # so we only forward it when present.
    filters = {"is_active": is_active}
    if organization_id is not None:
        filters["organization_id"] = organization_id
    return repo.list(**filters)
```

No ladder of `if param is not None`. The sentinel does the deciding.

## Ordering

`list` and `first` are unordered unless you ask. `order_by` takes one column or a
list of them:

```python
repo.list(order_by=User.created_at.desc())
repo.list(order_by=[User.created_at.desc(), User.id])
```

A tidy habit from real codebases: when a table has one canonical sort, declare it
once as a class attribute and reuse it everywhere.

```python
class UserRepository(Repository[User, UserDTO]):
    ORDER = User.created_at.desc()

repo.list(order_by=repo.ORDER)
```

Ordering becomes mandatory the moment you paginate. That is the subject of the
[pagination recipe](pagination.md).
