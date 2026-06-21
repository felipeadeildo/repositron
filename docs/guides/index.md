---
icon: lucide/chef-hat
---

# Guides

New here? [Concepts](../concepts.md) defines the vocabulary and [Get
started](../get-started.md) gives you a working repository. These guides then go
one capability at a time, each a self-contained read with examples drawn from the
kind of code repositories grow into: services that page through results, tasks
that batch-insert, queries that join across tables.

Read them in any order. Each opens with the problem it solves, so you can tell
at a glance whether it is the one you need right now.

<div class="grid cards" markdown>

-   :material-tune:{ .lg .middle } __[Configuration](configuration.md)__

    ---

    Type parameters, `field_mapping`, `pk_column`, and where behavior plugs in.
    Start here to understand how the base is customized.

-   :material-filter-variant:{ .lg .middle } __[Filtering](filtering.md)__

    ---

    Two ways to filter in a single call, and the special meaning of `None` and
    `UNSET` as filter values.

-   :material-null:{ .lg .middle } __[Updating rows](updates.md)__

    ---

    Partial updates that can tell "skip this field" apart from "set it to NULL".

-   :material-book-open-page-variant:{ .lg .middle } __[Pagination](pagination.md)__

    ---

    `list_paginated`, the total count it returns, and the order it insists on.

-   :material-table-column:{ .lg .middle } __[Projection](projection.md)__

    ---

    `repo[Shape]` to select only the columns a narrow shape declares.

-   :material-shape:{ .lg .middle } __[Return types](return-types.md)__

    ---

    Dataclass, model-as-DTO, or Pydantic, and when each fits.

-   :material-webhook:{ .lg .middle } __[Hooks](hooks.md)__

    ---

    Add to a write or a read with `@on`, a derived column, an enriched DTO, an
    audit row, without overriding anything.

-   :material-function-variant:{ .lg .middle } __[Custom queries](custom-queries.md)__

    ---

    Domain queries, batch inserts, and the `@writes` decorator, the
    raw-SQLAlchemy escape hatch for what the base does not cover.

-   :material-key:{ .lg .middle } __[Primary keys](primary-keys.md)__

    ---

    `int`, `str`, `uuid.UUID`, and tables whose key is not called `id`.

</div>
