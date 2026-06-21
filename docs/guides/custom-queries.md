---
icon: lucide/function-square
---

# Custom queries

The base class gives you CRUD. Real repositories grow past CRUD: a free-text
search, a batch insert, a query that joins three tables to answer one question.
repositron's job is to remove the boilerplate, not to box you in, so everything
on your repository is an ordinary class with `self.session` and `self.model_class`
to build on.

## Domain queries

A method that does not fit `get` / `list` is just a method. You have the session,
the model, and the full SQLAlchemy API:

```python
class UserRepository(Repository[User, UserDTO]):
    def active_in_org(self, organization_id: int) -> list[UserDTO]:
        return self.list(is_active=True, organization_id=organization_id)

    def deactivate_all_in_org(self, organization_id: int) -> None:
        self.session.query(User).filter(
            User.organization_id == organization_id
        ).update({User.is_active: False}, synchronize_session=False)
        self.session.flush()
```

Note the first method reuses `self.list` instead of reaching for the session.
Build on the inherited methods where they fit; drop to raw SQLAlchemy only where
they do not.

## Filter builders { #filter-builders }

When the same `WHERE` fragment shows up in several calls, a free-text search being
the classic case, give it a name. A method that returns a SQLAlchemy expression
plugs straight into `extra_filters`:

```python
from sqlalchemy import or_, ColumnElement


class UserRepository(Repository[User, UserDTO]):
    def search(self, q: str) -> ColumnElement[bool]:
        pattern = f"%{q}%"
        return or_(
            self.model_class.name.ilike(pattern),
            self.model_class.email.ilike(pattern),
        )


repo.list(extra_filters=[repo.search("ada")], is_active=True)
```

Callers express intent ("search for ada") and the column logic lives in one
place.

## Batch inserts

`create` inserts one row and reads its key back. For importing many rows at once,
the per-row flush is the wrong tool. Add a batch method that uses
`session.add_all` and flushes once:

```python
class UserRepository(Repository[User, UserDTO, UserCreate, UserUpdate]):
    def create_many(self, payloads: list[UserCreate]) -> None:
        if not payloads:
            return
        rows = [User(full_name=p.full_name, email=p.email) for p in payloads]
        self.session.add_all(rows)
        self.session.flush()
```

The same shape works for a batch that needs the generated ids back, by reading
them off the flushed models:

```python
    def create_many_returning(self, payloads: list[UserCreate]) -> list[int]:
        rows = [User(full_name=p.full_name, email=p.email) for p in payloads]
        self.session.add_all(rows)
        self.session.flush()
        return [r.id for r in rows]
```

## Custom hydration { #custom-hydration }

The automatic model-to-DTO conversion handles the common cases: a dataclass built
by field name, a Pydantic model through `model_validate`, or the model returned
as-is.

If you only need to *add* a derived field to the built DTO, a [`hydrate`
hook](hooks.md#enriching-the-dto) is the smaller move, it hands you the
finished DTO to enrich. Override `_hydrate` when the automatic build cannot
produce the DTO at all and you need to construct it yourself from scratch:

```python
class UserRepository(Repository[User, UserProfile]):
    def _hydrate(self, model: User) -> UserProfile:
        role_names = (
            self.session.query(Role.name)
            .join(UserRole, UserRole.role_id == Role.id)
            .filter(UserRole.user_id == model.id)
            .all()
        )
        return UserProfile(
            id=model.id,
            name=model.full_name,
            roles=[r.name for r in role_names],
        )
```

Once overridden, `_hydrate` runs for every read on that repository, so `get`,
`first`, and `list` all return fully-formed `UserProfile` objects. (Column
projection via `repo[Shape]` builds the narrow shape positionally and does not go
through `_hydrate`, which is what keeps a projection a pure column read.)

## A note on transactions

Custom writes should `flush`, never `commit`, the same as the base class, so they
compose inside the caller's transaction. See the
[design principles](../reference.md#design-principles).
