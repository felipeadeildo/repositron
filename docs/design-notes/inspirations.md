---
icon: lucide/sparkles
---

# Inspirations

repositron did not invent much. It borrowed good ideas from libraries that
solved adjacent problems well, and adapted them to a typed SQLAlchemy repository.
This page credits where each piece came from, so you can read the original
thinking, it is usually better written than ours.

## Hooks, from Pydantic validators

The [`@on`](../guides/hooks.md) decorator is modeled on
[Pydantic's validators](https://docs.pydantic.dev/latest/concepts/validators/).
Pydantic lets you tag a method to run at a precise point in a model's lifecycle,
a `field_validator`, a `model_validator(mode="before")`, without subclassing the
machinery or chaining `super()`. You declare *what* runs and *when*, and Pydantic
dispatches it.

That is exactly the shape we wanted for a repository: set a column before the
flush, enrich a DTO after the read, write an audit row, all without overriding
`create` or `_hydrate` and inheriting the parts you did not want to touch. The
`before` / `after` modes, the compose-across-mixins behavior, and the
"declare, don't override" philosophy are all lifted straight from how Pydantic
treats validation as a pipeline of tagged steps.

## Partial structures, from Prisma

[`repo[Shape]`](../guides/projection.md) projection, asking for a subset of
columns and getting a type that matches, comes from Prisma's
[operating against partial structures of model types](https://www.prisma.io/docs/orm/prisma-client/type-safety/operating-against-partial-structures-of-model-types).

Prisma's client lets you select a subset of fields and hands you back a type
narrowed to exactly that subset, no optional fields you have to null-check, no
full object you have to ignore half of. It leans on TypeScript's indexed access
types to prove the subset relationship statically. Python's type system can't
prove that part (see [typed primary keys](typed-keys.md) for why), so repositron
keeps the *ergonomics* of Prisma's partial selects, `repo[TaskCard].list()`,
and accepts a runtime check where Prisma gets a static one. The idea is Prisma's;
the seam is ours.

## Modern-Python feel, from SQLModel

The overall taste, lots of behavior from a single type declaration, sensible
defaults, great editor support, comes from
[SQLModel's feature philosophy](https://sqlmodel.tiangolo.com/features/).

SQLModel's pitch is that one annotated class should do the work of three, and
that the library's job is to *minimize what you write* while keeping the type
checker fully informed. repositron applies the same standard to the repository
layer: declare a model and a DTO, inherit one class, and the eight CRUD methods
arrive fully typed. The use of [PEP 695](https://peps.python.org/pep-0695/)
generics (`class Repository[Model, DTO]`), [PEP 696](https://peps.python.org/pep-0696/)
type-parameter defaults (`PKT = int`), and the dataclass-first return types are
all in the spirit of building on the newest Python the language offers, the same
bet SQLModel makes.

## The thread

All three share a conviction: **the type system is a tool for removing work, not
adding ceremony.** Pydantic removes the lifecycle plumbing, Prisma removes the
partial-shape guesswork, SQLModel removes the duplicate models. repositron tries
to remove the per-table repository. When something here feels obvious, it is
probably because one of these got the idea right first.
