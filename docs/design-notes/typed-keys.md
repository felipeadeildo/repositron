---
icon: lucide/key-round
---

# Typed primary keys

One question comes up often enough to deserve its own page: **why must I declare
the key type as `PKT` when I already told the repository which column the key is?**

```python
class AccountRepository(ReadOnlyRepository[Account, AccountDTO, str]):
    pk_column = Account.account_id   # this is clearly a str... why repeat it?
```

The short answer: Python's type system cannot read the type of `Account.account_id`
back into a generic parameter. The longer answer is a small tour of where Python's
static typing stands today, and it is worth reading once, because it shapes more
than just this library.

## The inspiration: TypeScript got there first

If you have written TypeScript, you have an instinct for what *should* happen here.
Tools like Prisma give you a primary-key type for free, inferred straight from the
schema:

```typescript
const user = await prisma.user.findUnique({
  where: { id: 42 },   // TS knows id is a number; "42" would be an error
})
```

TypeScript can do this because it has **indexed access types** and a **`typeof`
operator** that work on types, not just values:

```typescript
type UserId = User["id"]        // pluck the type of one field
type Repo   = typeof repoValue  // lift a value into the type world
```

Inference flows in both directions, so the compiler can look *into* a type and
pull a member's type out. That is the exact tool we would want: "the type of the
column named by `pk_column`". Python has no equivalent.

<figure markdown="span">
![Limited by the technology of our time](../images/limited-by-technology.webp){ width="520" }
<figcaption>The honest summary of typed primary-key inference in Python today.</figcaption>
</figure>

## Where Python's typing actually is

This is not an oversight in repositron; it is the current ceiling of the language.
A quick timeline of how typing for ORMs got to where it is:

| Version | PEP | What it gave us |
| ------- | --- | --------------- |
| 3.5 | [484](https://peps.python.org/pep-0484/) | `TypeVar` and the `typing` module. The start of static typing, but nothing dynamic. |
| 3.8 | [544](https://peps.python.org/pep-0544/) | `Protocol` (structural typing) and `TypedDict`. |
| 3.11 | [681](https://peps.python.org/pep-0681/) | `dataclass_transform`. The breakthrough that let SQLAlchemy 2.0 and Pydantic type their models, by telling the checker "treat my magic class like a dataclass". |
| 3.12 | [695](https://peps.python.org/pep-0695/) | The clean `class Repository[ModelT]:` syntax. Better to read; the inference rules did not change. |
| 3.13 | [696](https://peps.python.org/pep-0696/) | **Defaults for type parameters.** This is what lets `PKT = int` sit quietly at the end, so the common case never writes it. It is also why repositron requires Python 3.13. |

The two features that *would* close the gap, indexed access types
(`Model["id"]`) and a general `typeof`, are discussed in the `python/typing`
tracker but are not accepted for any release. The maintainers (the same people
who build pyright and mypy) have been candid that bolting them on would force a
near-rewrite of the checkers and risk pathological inference times.

There is one draft that aims squarely at this: [PEP 827 – Type
Manipulation](https://peps.python.org/pep-0827/), published in early 2026. It
proposes the TypeScript-style toolkit wholesale, conditional types, type
comprehensions, and crucially a `GetMemberType[T, S]` that would extract a
member's type from a model, exactly the operation we want. But it is a **draft
under discussion**, not accepted and not implemented, and it draws real pushback:
the syntactic density it introduces (Haskell-ish nested type expressions,
conditional type logic) cuts against Python's preference for a type system that
stays readable. Betting a library's public API on it today would be betting on a
proposal that may never land in this form.

So the feature we want is genuinely not on the roadmap. We are, briefly, limited
by the technology of our time.

## Two rules that follow from this

Two specific facts about Python's checker explain why `pk_column = Model.id`
cannot drive the type, and both are working as designed:

1. **A `ClassVar` cannot carry a type parameter** ([PEP 526](https://peps.python.org/pep-0526/)).
   You cannot stash `PKT` in `pk_column` and have the methods read it back.
2. **Inheritance is resolved before the class body.** When the checker reads
   `class AccountRepository(ReadOnlyRepository[Account, AccountDTO, str])`, the
   parameters are pinned at that line. A `pk_column = ...` assignment *inside* the
   body comes too late to influence them.

This is the same wall every Python ORM hits. `advanced-alchemy`, for instance,
types its id argument as `Any` and leans on composite-key support instead, the
deeper reason precise key typing is a dead end in general: a two-column key has no
single type to infer anyway.

## How we landed on `repo[Shape]`

The key type was the *last* typing wall we hit. The first, and the one that
shaped the whole API, was a different question: **how do you return a partial row
without lying about its type?**

The starting point was the obvious generic repository: a `Repository[Model, DTO]`
where every read hydrates the full DTO.

```python
@dataclass(slots=True)
class UserDTO:
    id: int
    first_name: str
    last_name: str

repo.first()   # -> UserDTO, always all three columns
```

That is fine until you only need `first_name`. The query still selects every
column, and the DTO still carries every field. You want to ask for a subset, and
have the *type* narrow to match. Each attempt to express that ran into a wall:

- **Make the DTO fields optional.** `first_name: str | None`, then check
  `if dto.first_name is not None` everywhere. This poisons every call site with
  runtime `None`-checks for fields you *know* are present, the type lost the very
  information that made it useful.
- **Use a `TypedDict` instead of a dataclass.** It models partial shapes, but a
  dict carries more memory overhead than a `slots=True` dataclass and loses the
  attribute-access ergonomics. We picked dataclasses precisely for the lean
  footprint; trading it back for partial typing was a bad deal.
- **Lean on [PEP 695](https://peps.python.org/pep-0695/) type parameters.** The
  clean `class Repository[Model, DTO]` syntax is lovely, but a type parameter is
  a static-only thing, you can't pull the chosen shape *back out* at runtime to
  build the `SELECT`. Same wall as the key type, one layer up.

The breakthrough was to stop trying to encode the shape in the *class* and encode
it per *call*, with `__getitem__`:

```python
repo[UserCard].first()   # SELECT first_name; returns UserCard, typed
```

`repo[Shape]` returns a lightweight clone of the repository bound to `Shape` for
the next call, **clone-and-cast**: `copy.copy(self)` plus a `cast` to
`Repository[Model, Shape]`. The runtime gets the shape (to project the columns
and build the narrow object); the type checker gets the cast (so the return type
is `Shape`, not the full DTO). The two needs that couldn't be met by one
mechanism are split across the two worlds that can each serve one of them. The
[projection recipe](../guides/projection.md) covers it from the user's side.

It is a small amount of extra code, and it buys the signature we wanted all
along: `repo[UserCard].first(...) -> UserCard | None`. The alternatives we
weighed and rejected, currying (`repo.first(Shape)(...)`) or a `shape=` keyword
argument, either traded one kind of boilerplate for another (a fan of
`_FirstCurried` / `_ListCurried` protocols to keep the curried calls typed) or
gave up the projection sugar entirely. `repo[Shape]` reads cleanly at the call
site and keeps the internals small, so it won.

The honest footnote, the same one that governs the key type: the projection
mechanism is runtime-checked, not statically guaranteed to be a *subset* of the
model. If `Shape` names a field the model doesn't have, you find out at the
query, not at the type level. Indexed access types would let the checker prove
the subset relationship; until then, the cast is the seam where we trade a static
guarantee for a runtime one, deliberately, and in one place.

## The design we chose

Given the constraint, the goal was the least boilerplate that still type-checks
honestly:

- **`PKT` defaults to `int`.** Most tables are keyed by an integer, so most
  repositories declare nothing and still get a checked id, `repo.get("oops")` is
  an error with zero extra typing.
- **`PKT` is the last type parameter.** A non-int key costs exactly one token
  (`str`, `uuid.UUID`) in a slot the common case never touches.
- **`pk_column` accepts a column reference at runtime.** `pk_column = Page.url_hash`
  is checked against the model and reads naturally, even though, per the rules
  above, it cannot feed the static key type. That stays in `PKT`.

The split is deliberate: the column's **name** is a runtime concern
(`pk_column`), the key's **type** is a static one (`PKT`). Python cannot bridge
them for us, so we state each in the one place that can.

You declare the key type exactly once. There is no projection that avoids it,
and pretending otherwise would mean lying to the checker. When indexed access
types land in some future Python, this page gets shorter.
