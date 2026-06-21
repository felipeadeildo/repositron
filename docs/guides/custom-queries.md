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

For the rest, the question is *add* or *replace*:

- To **add** a derived field to the built DTO, use a [`hydrate` hook](hooks.md#enriching-the-dto).
  It hands you the finished DTO to enrich, so you write one field, not all of them.
- To **replace** the build, when the automatic path cannot produce the DTO at
  all, override `_hydrate` and construct it yourself:

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

`_hydrate` then runs for every read, so `get`, `first`, and `list` all return
fully-formed `UserProfile` objects. (Column projection via `repo[Shape]` builds
the narrow shape positionally and does not go through `_hydrate`, which keeps a
projection a pure column read.)

Overriding `_hydrate` and tagging a method with
[`@on("hydrate", mode="build")`](hooks.md#replacing-the-build) are the same
mechanism, the override is just the build hook spelled as a method. Use whichever
reads better: the override for a longer construction like the one above, the hook
for a one-liner.

## Transactions on custom writes { #writes }

A custom write is responsible for the same `flush` / `commit` / rollback dance
the built-in `create` / `update` / `delete` handle for you. `@writes` gives a
custom method that dance, so its body is only the session work:

```python
from repositron import Repository, writes


class CitationRepository(Repository[Citation, CitationDTO, CitationCreate, CitationUpdate]):
    @writes
    def upsert(self, payload: CitationCreate) -> None:
        stmt = pg_insert(Citation).values(...).on_conflict_do_update(...)
        self.session.execute(stmt)   # flushed for you; rolled back on error
```

The decorated method flushes after the body, commits if the repository is
`autocommit=True`, and rolls back on error, exactly like the built-in writes (see
[committing](updates.md#transactions)). To let a caller commit a single write,
declare a `commit` parameter and `@writes` honors it:

```python
    @writes
    def upsert(self, payload: CitationCreate, *, commit: bool | None = None) -> None:
        self.session.execute(...)


repo.upsert(payload, commit=True)   # this one write commits
```

When the method needs the primary key mid-way, to attach child rows or return it,
flush yourself at that point. `@writes` still owns the final flush and the
commit/rollback:

```python
    @writes
    def create_with_lines(self, payload: InvoiceCreate) -> int:
        invoice = Invoice(customer_id=payload.customer_id)
        self.session.add(invoice)
        self.session.flush()        # need invoice.id for the lines below
        for line in payload.lines:
            self.session.add(InvoiceLine(invoice_id=invoice.id, sku=line.sku))
        return invoice.id
```

Without `@writes`, a custom write should still `flush`, never `commit`, the same
as the base class, so it composes inside the caller's transaction. See the
[design principles](../reference.md#design-principles).
