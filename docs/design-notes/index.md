---
icon: lucide/book-open
---

# Design notes

This section is for the curious, the developer who wants to know not just *how*
to use repositron but *why* it is shaped the way it is. Every feature here came
from a real problem in a real codebase, and most of the interesting design work
was in saying no to the obvious-but-wrong solution.

## Where it came from

repositron was extracted from the data layer of [RanqIA](https://ranqia.ai), a
production application with a lot of tables. Like every SQLAlchemy project of that
size, it grew a repository per table, and every one of those repositories was
80% the same code: the same `get` / `list` / `count`, the same pagination, the
same model-to-DTO conversion, copied and tweaked. The duplication was not just
tedious; it was where bugs lived, a pagination that forgot its `count`, a DTO
that drifted from its model, a filter that handled `None` one way here and another
way there.

The fix was to write that 80% once, generically and typed, and let each table
declare only the 20% that is actually its own. That is the whole library. But
"generic and typed" is where it got interesting, because Python's type system
does not always cooperate, and because real repositories need to do more than
plain CRUD.

## Features are answers to problems

Each piece of repositron exists because the application needed it. The pattern
was always the same: a repository in the codebase was doing something by hand,
the same way in several places, and that repetition was the signal that the base
class should absorb it.

- **Hooks** came from repositories overriding `create` just to stamp a timestamp
  or normalize an email, inheriting all the `add` / `flush` / return-the-id
  plumbing they did not want to touch. The answer was to let them
  [declare the one step that was theirs](../guides/hooks.md) and keep the rest.
- **The `build` hook** came from a repository whose DTO was a plain `str`, a
  cached image URL, which the automatic conversion could not produce. Rather than
  make `_hydrate` override the only escape hatch, we made
  [DTO construction itself a hook](../guides/hooks.md#replacing-the-build) the
  base registers and a subclass can replace, so the base eats its own dog food.
- **`@writes`** came from custom write methods, an upsert here, a create-with-
  children there, each hand-rolling `flush` / `commit` / rollback and getting the
  edge cases subtly different. The answer was to
  [give a custom write the same transaction handling](../guides/custom-queries.md#writes)
  the built-ins already had.
- **`repo[Shape]` projection** came from wanting to `SELECT` two columns instead
  of twelve and get a *type* that matched, which turned out to be one of the
  harder problems in the whole library. The full story is in
  [typed primary keys](typed-keys.md#how-we-landed-on-reposhape).

## The two pages here

- **[Inspirations](inspirations.md)** credits the libraries each idea was
  borrowed from, Pydantic's validators, Prisma's partial types, SQLModel's
  modern-Python feel.
- **[Typed primary keys](typed-keys.md)** is the deepest design note: why you
  declare the key type as `PKT` even after naming the key column, a tour of where
  Python's static typing stands today, and how the same wall shaped `repo[Shape]`.

If you only want to *use* repositron, the [guides](../guides/index.md) are
enough. This section is the part you read when you want to know how the sausage
was made, and maybe disagree with a choice or two.
