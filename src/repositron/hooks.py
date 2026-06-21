"""
Lifecycle hooks: tag a method with `@on` and the repository runs it inside its
own create/update/delete/hydration, with no override and no `super()` chaining.

    class ArticleRepository(Repository[Article, ...]):
        @on("create", mode="before")
        def stamp_published(self, model, payload):
            model.published_at = datetime.now(UTC)

The base collects tagged methods across the MRO at class-definition time, so
hooks compose across mixins and base classes, firing in base-to-subclass order.
`Repository` documents the events and what each passes.
"""

from collections.abc import Callable
from typing import Literal, get_args

HookEvent = Literal["create", "update", "delete", "hydrate"]
"""The repository operation a hook attaches to."""

HookMode = Literal["before", "after"]
"""When a hook runs: before/after the operation's core (flush for writes, DTO build for hydrate)."""

type HookKey = tuple[HookEvent, HookMode]

VALID_HOOKS: frozenset[HookKey] = frozenset(
    (event, mode) for event in get_args(HookEvent) for mode in get_args(HookMode)
) - {("hydrate", "before")}
"""Every (event, mode) pair except `hydrate`/`before`: there is nothing to act on before a read builds the DTO."""  # noqa: E501

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
                names = registry.setdefault(key, [])
                if name not in names:
                    names.append(name)
    return registry
