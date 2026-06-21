"""
Lifecycle hooks: tag a method with `@on` to run it inside a create, update,
delete, or read, with no method override and no `super()` chaining.

```python
class ArticleRepository(Repository[Article, ...]):
    @on("create", mode="before")
    def stamp_published(self, model, payload):
        model.published_at = datetime.now(UTC)
```

Hooks compose: stack `@on` for several events on one method, and hooks from
mixins and base classes all fire, in base-to-subclass order. `Repository` lists
every event and the arguments it passes.
"""

from collections.abc import Callable
from typing import Literal

HookEvent = Literal["create", "update", "delete", "hydrate"]
"""The repository operation a hook attaches to."""

HookMode = Literal["before", "build", "after"]
"""When a hook runs: `before`/`after` the operation, or `build` (hydrate only) to construct the DTO."""  # noqa: E501

type HookKey = tuple[HookEvent, HookMode]

BUILD_HOOK: HookKey = ("hydrate", "build")
"""The hydrate `build` hook. Unlike before/after, only the most-derived one runs."""

# before/after on every event, except hydrate/before (nothing precedes a read's DTO build);
# build is hydrate-only (writes have no DTO to construct).
VALID_HOOKS: frozenset[HookKey] = frozenset(
    {
        ("create", "before"),
        ("create", "after"),
        ("update", "before"),
        ("update", "after"),
        ("delete", "before"),
        ("delete", "after"),
        ("hydrate", "after"),
        BUILD_HOOK,
    }
)
"""Valid (event, mode) pairs: before/after on every event (minus hydrate/before), plus hydrate/build."""  # noqa: E501

_HOOK_ATTR = "__repositron_hooks__"


def on(event: HookEvent, *, mode: HookMode) -> Callable[[Callable], Callable]:
    """
    Tag a repository method to run on `event` at `mode`.

    The method is dispatched by the repository, not called directly; its
    signature per event is documented on `Repository`. Stack `@on` to register
    the same method on several events.
    """

    def mark(func: Callable) -> Callable:
        existing = getattr(func, _HOOK_ATTR, ())
        setattr(func, _HOOK_ATTR, (*existing, (event, mode)))
        return func

    return mark


type HookRegistry = dict[HookKey, list[str]]
"""Collected hooks: `registry[(event, mode)]` is the ordered list of method names to run."""


def collect_hooks(cls: type) -> HookRegistry:
    """
    Build the hook registry for `cls` by scanning its MRO base-to-subclass.

    Stores method names (not functions), so a subclass override of a tagged
    method is the one that runs. A base class's hook runs before a subclass's.

    The `build` hook is single-winner: the most-derived one replaces any
    inherited build, so a subclass's build overrides the base default.

    Raises:
        TypeError: if a method is tagged with an unknown (event, mode) pair.

    """
    registry: HookRegistry = {}
    # reversed(MRO) is object -> base -> subclass: outermost base hooks run first.
    for klass in reversed(cls.__mro__):
        for name, member in vars(klass).items():
            for key in getattr(member, _HOOK_ATTR, ()):
                if key not in VALID_HOOKS:
                    raise TypeError(f"{cls.__name__}.{name}: unknown hook {key!r}")
                if key == BUILD_HOOK:
                    # Single winner: most-derived build replaces the inherited one.
                    registry[key] = [name]
                    continue
                names = registry.setdefault(key, [])
                if name not in names:
                    names.append(name)
    return registry
