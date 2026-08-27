"""Lifecycle hooks and the transaction wrapper for custom writes."""

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Concatenate, Literal, Protocol, cast, overload

HookEvent = Literal["create", "update", "delete", "hydrate"]
HookMode = Literal["before", "build", "after"]
type HookKey = tuple[HookEvent, HookMode]
type HookRegistry = dict[HookKey, list[str]]

BUILD_HOOK: HookKey = ("hydrate", "build")
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
_HOOK_ATTR = "__repositron_hooks__"


class _SyncWriteRepository(Protocol):
    def _flush_sync(self) -> None: ...
    def _run_sync[R](self, op: Callable[[], R]) -> R: ...
    def _commit_sync(self, commit: bool | None) -> None: ...


class _AsyncWriteRepository(Protocol):
    async def _flush_async(self) -> None: ...
    async def _run_async[R](self, op: Callable[[], Awaitable[R]]) -> R: ...
    async def _commit_async(self, commit: bool | None) -> None: ...


def on(event: HookEvent, *, mode: HookMode) -> Callable[[Callable], Callable]:
    """Register a method as a lifecycle hook."""

    def mark(func: Callable) -> Callable:
        existing = getattr(func, _HOOK_ATTR, ())
        setattr(func, _HOOK_ATTR, (*existing, (event, mode)))
        return func

    return mark


def collect_hooks(cls: type) -> HookRegistry:
    """Collect tagged hook names in base-to-subclass order."""
    registry: HookRegistry = {}
    for klass in reversed(cls.__mro__):
        for name, member in vars(klass).items():
            for key in getattr(member, _HOOK_ATTR, ()):
                if key not in VALID_HOOKS:
                    raise TypeError(f"{cls.__name__}.{name}: unknown hook {key!r}")
                if key == BUILD_HOOK:
                    registry[key] = [name]
                    continue
                names = registry.setdefault(key, [])
                if name not in names:
                    names.append(name)
    return registry


@overload
def writes[T, **P, R](
    method: Callable[Concatenate[T, P], Awaitable[R]],
) -> Callable[Concatenate[T, P], Awaitable[R]]: ...


@overload
def writes[T, **P, R](
    method: Callable[Concatenate[T, P], R],
) -> Callable[Concatenate[T, P], R]: ...


def writes(method: Callable[..., object]) -> Callable[..., object]:
    """
    Apply the repository's flush, commit, and rollback policy to a custom write.

    A synchronous function is for ``*_sync`` use. An ``async def`` function is
    for the awaited API. The repository raises a clear error if callers use the
    function through the wrong session mode.
    """
    if inspect.iscoroutinefunction(method):

        @functools.wraps(method)
        async def async_wrapper(self: object, *args: object, **kwargs: object) -> object:
            commit = cast("bool | None", kwargs.pop("commit", None))
            repo = cast("_AsyncWriteRepository", self)
            async_method = cast("Callable[..., Awaitable[object]]", method)

            async def op() -> object:
                result = await async_method(repo, *args, **kwargs)
                await repo._flush_async()
                return result

            result = await repo._run_async(op)
            await repo._commit_async(commit)
            return result

        return async_wrapper

    @functools.wraps(method)
    def sync_wrapper(self: object, *args: object, **kwargs: object) -> object:
        commit = cast("bool | None", kwargs.pop("commit", None))
        repo = cast("_SyncWriteRepository", self)

        def op() -> object:
            result = method(repo, *args, **kwargs)
            repo._flush_sync()
            return result

        result = repo._run_sync(op)
        repo._commit_sync(commit)
        return result

    return sync_wrapper
