---
icon: lucide/house
hide:
  - navigation
  - toc
---

# repositron

<p style="font-size: 1.25rem; opacity: 0.8;">
A typed, generic repository base for SQLAlchemy 2.0.<br>
Full CRUD, with <strong>zero per-table boilerplate</strong>.
</p>

[Get started](get-started.md){ .md-button .md-button--primary }
[Recipes](recipes/index.md){ .md-button }

---

Every SQLAlchemy project ends up with the same folder: one repository class per
table, each wrapping `session.query(...)` in the same `get`, the same `list`,
the same pagination math. repositron writes that layer once, generically, and
types it against your model and your return shape.

=== ":material-close-circle: Hand-written, per table"

    ```python
    class UserRepository:
        def __init__(self, session: Session) -> None:
            self.session = session

        def get(self, id: int) -> UserDTO | None:
            row = self.session.query(User).filter(User.id == id).first()
            if row is None:
                return None
            return UserDTO(id=row.id, name=row.full_name, email=row.email)

        def list(self, *, is_active: bool | None = None) -> list[UserDTO]:
            query = self.session.query(User)
            if is_active is not None:
                query = query.filter(User.is_active == is_active)
            return [UserDTO(id=r.id, name=r.full_name, email=r.email) for r in query.all()]

        def update(self, id: int, *, full_name: str | None = None) -> bool:
            user = self.session.query(User).filter(User.id == id).first()
            if user is None:
                return False
            if full_name is not None:   # and how do you null it on purpose?
                user.full_name = full_name
            self.session.flush()
            return True

        # ...count, delete, first, pagination, then again for the next ten tables.
    ```

=== ":material-check-circle: Declared once"

    ```python
    from dataclasses import dataclass
    from repositron import Repository, UNSET, UnsetType


    @dataclass(frozen=True, slots=True)
    class UserDTO:               # light, detached, serializes straight to JSON
        id: int
        name: str                # renamed from the model column `full_name`
        email: str


    @dataclass
    class UserUpdate:
        full_name: str | UnsetType = UNSET   # absent leaves it; None sets NULL


    class UserRepository(Repository[User, UserDTO, UserCreate, UserUpdate]):
        field_mapping = {"full_name": "name"}
    ```

    Every method from the other tab now exists, typed against `UserDTO`, with no
    further code.

## What you get

<div class="grid cards" markdown>

-   :material-shield-check:{ .lg .middle } __Typed end to end__

    ---

    `repo.list()` is `list[UserDTO]`, and your editor knows it. No casts, no
    `Any`. The return value is the same object your API serializes.

-   :material-filter-variant:{ .lg .middle } __Two ways to filter, one call__

    ---

    Equality by keyword and arbitrary SQLAlchemy expressions, combined. You never
    pick between readable and powerful.

    [:octicons-arrow-right-24: Filtering](recipes/filtering.md)

-   :material-null:{ .lg .middle } __Updates that write NULL on purpose__

    ---

    `UNSET` leaves a column alone; `None` sets it to `NULL`. The `is not None`
    pattern cannot tell those apart. repositron can.

    [:octicons-arrow-right-24: Updates & UNSET](recipes/updates.md)

-   :material-table-column:{ .lg .middle } __Load only what you need__

    ---

    `repo[Card].list()` selects just that shape's columns, for one call, without
    touching the injected repository.

    [:octicons-arrow-right-24: Projection](recipes/projection.md)

-   :material-book-open-page-variant:{ .lg .middle } __Pagination that refuses to lie__

    ---

    `list_paginated` requires `order_by` and raises if you forget, turning a
    production heisenbug into an error at the call site.

    [:octicons-arrow-right-24: Pagination](recipes/pagination.md)

-   :material-feather:{ .lg .middle } __One dependency__

    ---

    Just `sqlalchemy>=2.0`. Dataclass DTOs add nothing else; Pydantic is detected
    only if your DTO is one.

</div>

## Install { style="text-align: center" }

<div style="max-width: 22rem; margin: 0 auto;" markdown>

=== "uv"

    ```bash
    uv add repositron
    ```

=== "pip"

    ```bash
    pip install repositron
    ```

</div>

<p style="text-align: center;">Python 3.13+ and <code>sqlalchemy>=2.0</code>.</p>

[Get started](get-started.md){ .md-button .md-button--primary }
{ style="text-align: center" }
