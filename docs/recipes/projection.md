---
icon: lucide/columns-3
---

# Projection

Sometimes you have a twenty-column table and a screen that shows three of them.
Loading the whole row to throw most of it away is wasteful, and it is exactly the
sort of thing you stop noticing until a list endpoint gets slow.

## Ask for a narrower shape

Index the repository with a smaller dataclass and that one call selects only the
columns that shape declares, and returns instances of it:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserCard:
    id: int
    name: str

repo[UserCard].list(is_active=True)   # SELECT id, name -> list[UserCard]
repo[UserCard].first(id=5)            # UserCard | None
```

The generated SQL is a real column projection. The database reads and ships only
those columns, and you get back `UserCard` objects, not full `User` rows you then
have to trim.

## It does not disturb the repository you injected

`repo[UserCard]` returns a lightweight clone bound to that shape for the duration
of the call. The repository you constructed and injected is untouched, so this is
safe to do anywhere, including in code that shares one repository across requests:

```python
repo.list()                  # list[UserDTO]   (the repository's default shape)
repo[UserCard].list()        # list[UserCard]  (just for this call)
repo.list()                  # list[UserDTO]   (unchanged; still the default)
```

Because the clone is cheap and stateless, reaching for a projection is never a
structural decision. It is a per-call detail.

## Field renames carry over

A projected shape can use the renamed field name; the repository's
[`field_mapping`](configuration.md#field_mapping) resolves it back to the column,
the same as for the full DTO.

```python
@dataclass(frozen=True, slots=True)
class UserCard:
    id: int
    name: str        # field_mapping resolves this to the full_name column

repo[UserCard].list()   # SELECT id, full_name
```

## Where it pays off

Two patterns recur:

- **Lookups.** When you need an `id -> something` map and nothing else, project
  to just those two columns and build the dict:

    ```python
    rows = repo[UserIdName].list(extra_filters=[User.id.in_(wanted)])
    names = {r.id: r.name for r in rows}
    ```

- **Fan-out.** When a background job needs a list of ids and one flag to decide
  what to enqueue, projecting to that pair avoids hydrating rows you will not
  otherwise use:

    ```python
    for row in repo[UserIdActive].list():
        if row.is_active:
            enqueue(row.id)
    ```

Projection also composes with [pagination](pagination.md#pagination-plays-well-with-projection),
so a paginated card list fetches only the card's columns.
