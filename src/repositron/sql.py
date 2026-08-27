"""Unified synchronous and asynchronous SQLAlchemy repositories."""

import copy
import inspect as pyinspect
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import fields, is_dataclass
from functools import cached_property
from typing import ClassVar, cast, get_args, get_origin

from sqlalchemy import CursorResult, Delete, Select, Update, delete, func, inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session
from sqlalchemy.orm import InstrumentedAttribute, Mapper, Session
from sqlalchemy.sql.elements import ColumnElement

from repositron.base import (
    AsyncRepositorySession,
    FilterValue,
    OrderBy,
    PaginatedResult,
    RepositorySession,
)
from repositron.hooks import HookEvent, HookMode, HookRegistry, collect_hooks, on
from repositron.sentinel import UnsetType

_list = list


class _HookedRepository:
    """Validate hook declarations as repository subclasses are created."""

    _hooks: ClassVar[HookRegistry] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls._hooks = collect_hooks(cls)


class ReadOnlyRepository[ModelT, DTOT = ModelT, PKT = int, SessionT: RepositorySession = Session](
    _HookedRepository
):
    """
    Read one model through either a :class:`Session` or :class:`AsyncSession`.

    The regular methods are the asynchronous API and require ``AsyncSession``.
    Their ``*_sync`` counterparts require ``Session``. Statement construction,
    DTO hydration, projection, filtering, and ordering stay identical in both
    modes.
    """

    field_mapping: ClassVar[dict[str, str]] = {}
    pk_column: ClassVar[str | InstrumentedAttribute] = "id"

    def __init__(
        self,
        session: SessionT,
        *,
        autocommit: bool = False,
        rollback_on_error: bool = True,
    ) -> None:
        """Store a caller-owned synchronous or asynchronous SQLAlchemy session."""
        self.session = session
        self.autocommit = autocommit
        self.rollback_on_error = rollback_on_error
        self._active_dto: type | None = None

    def _sync_session(self) -> Session:
        if isinstance(self.session, (AsyncSession, async_scoped_session)):
            raise TypeError(
                f"{type(self).__name__} has an AsyncSession; use the awaited repository method"
            )
        return self.session

    def _async_session(self) -> AsyncRepositorySession:
        if not isinstance(self.session, (AsyncSession, async_scoped_session)):
            raise TypeError(
                f"{type(self).__name__} has {type(self.session).__name__}; "
                "use the matching *_sync repository method"
            )
        return self.session

    @staticmethod
    def _sync_value(value: object, source: str) -> object:
        if not pyinspect.isawaitable(value):
            return value
        close = getattr(value, "close", None)
        if close is not None:
            close()
        raise TypeError(f"{source} returned an awaitable; use the awaited repository method")

    @staticmethod
    async def _async_value(value: object) -> object:
        return await value if pyinspect.isawaitable(value) else value

    def _hooks_for(self, event: HookEvent, mode: HookMode) -> Iterator[Callable[..., object]]:
        for name in self._hooks.get((event, mode), ()):
            hook = getattr(self, name, None)
            if not callable(hook):
                raise TypeError(f"Hook {type(self).__name__}.{name} must be callable")
            yield hook

    @staticmethod
    def _hook_name(hook: Callable[..., object]) -> str:
        name = getattr(hook, "__qualname__", None)
        return name if isinstance(name, str) else type(hook).__name__

    def _emit_sync(self, event: HookEvent, mode: HookMode, *args: object) -> None:
        for hook in self._hooks_for(event, mode):
            self._sync_value(hook(*args), f"hook {self._hook_name(hook)}")

    async def _emit_async(self, event: HookEvent, mode: HookMode, *args: object) -> None:
        for hook in self._hooks_for(event, mode):
            await self._async_value(hook(*args))

    def _run_sync[R](self, op: Callable[[], R]) -> R:
        """Run synchronous database work and roll back on errors when configured."""
        session = self._sync_session()
        try:
            return op()
        except Exception:
            if self.rollback_on_error:
                session.rollback()
            raise

    async def _run_async[R](self, op: Callable[[], Awaitable[R]]) -> R:
        """Run asynchronous database work and roll back on errors when configured."""
        session = self._async_session()
        try:
            return await op()
        except Exception:
            if self.rollback_on_error:
                await session.rollback()
            raise

    def _flush_sync(self) -> None:
        self._run_sync(self._sync_session().flush)

    async def _flush_async(self) -> None:
        session = self._async_session()
        await self._run_async(session.flush)

    def _commit_sync(self, commit: bool | None) -> None:
        if commit if commit is not None else self.autocommit:
            self._run_sync(self._sync_session().commit)

    async def _commit_async(self, commit: bool | None) -> None:
        if commit if commit is not None else self.autocommit:
            session = self._async_session()
            await self._run_async(session.commit)

    @classmethod
    def _extract_type_arg(cls, index: int) -> type | None:
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base) or base
            if isinstance(origin, type) and issubclass(origin, ReadOnlyRepository):
                args = get_args(base)
                if len(args) > index:
                    arg = args[index]
                    return arg if isinstance(arg, type) else None
                return None
        raise TypeError(
            f"Cannot infer type arguments for {cls.__name__}. Inherit from Repository[Model, ...]."
        )

    @cached_property
    def model_class(self) -> type[ModelT]:
        model = self._extract_type_arg(0)
        if model is None:
            raise TypeError(f"{type(self).__name__} must be parameterized with a model class.")
        return cast("type[ModelT]", model)

    @cached_property
    def dto_class(self) -> type[DTOT]:
        dto = self._extract_type_arg(1)
        return cast("type[DTOT]", dto if dto is not None else self.model_class)

    @property
    def _dto(self) -> type:
        return self._active_dto if self._active_dto is not None else self.dto_class

    def __getitem__[S](self, dto: type[S]) -> "ReadOnlyRepository[ModelT, S, PKT, SessionT]":
        """Bind a projection DTO for one call without changing this repository."""
        clone = copy.copy(self)
        clone._active_dto = dto
        return cast("ReadOnlyRepository[ModelT, S, PKT, SessionT]", clone)

    @cached_property
    def _pk_col(self) -> InstrumentedAttribute:
        pk = type(self).pk_column
        name = pk if isinstance(pk, str) else pk.key
        col = getattr(self.model_class, name, None)
        if col is None:
            raise AttributeError(f"{self.model_class.__name__} has no column '{name}'")
        return col

    def _project_columns(self, dto: type) -> _list[ColumnElement]:
        reverse = {v: k for k, v in self.field_mapping.items()}
        if not is_dataclass(dto):
            raise TypeError(f"DTO {dto.__name__} must be a dataclass")
        names = [field.name for field in fields(dto)]
        if not names:
            raise ValueError(f"DTO {dto.__name__} has no fields")
        columns: _list[ColumnElement] = []
        for name in names:
            model_field = reverse.get(name, name)
            col = getattr(self.model_class, model_field, None)
            if col is None:
                raise AttributeError(
                    f"DTO {dto.__name__}: field '{name}' maps to no column on "
                    f"{self.model_class.__name__} (model_field='{model_field}')"
                )
            columns.append(col)
        return columns

    def _filter_clauses(self, **filters: FilterValue) -> _list[ColumnElement[bool]]:
        clauses: _list[ColumnElement[bool]] = []
        for key, value in filters.items():
            if isinstance(value, UnsetType):
                continue
            if not hasattr(self.model_class, key):
                raise ValueError(f"{self.model_class.__name__} has no attribute '{key}'")
            clauses.append(getattr(self.model_class, key) == value)
        return clauses

    def _apply_filters(
        self,
        stmt: Select,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        **filters: FilterValue,
    ) -> Select:
        clauses = self._filter_clauses(**filters)
        if clauses:
            stmt = stmt.where(*clauses)
        if extra_filters:
            stmt = stmt.where(*extra_filters)
        return stmt

    def _apply_order(self, stmt: Select, order_by: OrderBy = None) -> Select:
        if order_by is None:
            return stmt
        return stmt.order_by(*order_by) if isinstance(order_by, list) else stmt.order_by(order_by)

    def _select(
        self,
        *columns: ColumnElement,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> Select:
        stmt = select(*columns) if columns else select(self.model_class)
        return self._apply_order(
            self._apply_filters(stmt, extra_filters=extra_filters, **filters), order_by=order_by
        )

    def _project(
        self,
        dto: type,
        *,
        extra_filters: _list[ColumnElement[bool]] | None,
        order_by: OrderBy,
        **filters: FilterValue,
    ) -> Select:
        return self._select(
            *self._project_columns(dto),
            extra_filters=extra_filters,
            order_by=order_by,
            **filters,
        )

    def _projecting(self) -> type | None:
        shape = self._active_dto
        if shape is None or shape is self.model_class:
            return None
        return shape if is_dataclass(shape) else None

    @on("hydrate", mode="build")
    def _hydrate(self, model: ModelT) -> DTOT:
        """Build the configured DTO from a loaded model."""
        dto = self._dto
        if dto is self.model_class:
            return cast("DTOT", model)
        try:
            validate = getattr(dto, "model_validate", None)
            if validate is not None:
                return cast("DTOT", validate(model))
            model_dict = {
                key: value for key, value in model.__dict__.items() if not key.startswith("_")
            }
            if is_dataclass(dto):
                reverse = {v: k for k, v in self.field_mapping.items()}
                return cast(
                    "DTOT",
                    dto(
                        **{
                            field.name: model_dict[reverse.get(field.name, field.name)]
                            for field in fields(dto)
                            if reverse.get(field.name, field.name) in model_dict
                        }
                    ),
                )
            return cast("DTOT", dto(**model_dict))
        except (AttributeError, TypeError, IndexError) as error:
            raise NotImplementedError(
                f"Cannot automatically convert {type(model).__name__} to {dto.__name__}. "
                f"Override _hydrate() in your repository subclass. Error: {error}"
            ) from error

    @cached_property
    def _build_hook(self) -> Callable[[ModelT], object]:
        return next(self._hooks_for("hydrate", "build"), self._hydrate)

    @cached_property
    def _after_hooks(self) -> _list[Callable[..., object]]:
        return list(self._hooks_for("hydrate", "after"))

    def _hydrate_one_sync(self, model: ModelT) -> DTOT:
        """
        Build one DTO for a custom synchronous repository method.

        Uses the selected hydrate build hook and every hydrate after-hook.
        """
        dto = cast("DTOT", self._sync_value(self._build_hook(model), "hydrate build hook"))
        for hook in self._after_hooks:
            dto = cast("DTOT", self._sync_value(hook(model, dto), f"hook {self._hook_name(hook)}"))
        return dto

    async def _hydrate_one_async(self, model: ModelT) -> DTOT:
        """
        Build one DTO for a custom asynchronous repository method.

        Uses the selected hydrate build hook and awaits every hydrate after-hook.
        """
        dto = cast("DTOT", await self._async_value(self._build_hook(model)))
        for hook in self._after_hooks:
            dto = cast("DTOT", await self._async_value(hook(model, dto)))
        return dto

    def _read_stmt(
        self,
        *,
        extra_filters: _list[ColumnElement[bool]] | None,
        order_by: OrderBy,
        filters: dict[str, FilterValue],
    ) -> tuple[type | None, Select]:
        dto = self._projecting()
        stmt = (
            self._project(dto, extra_filters=extra_filters, order_by=order_by, **filters)
            if dto is not None
            else self._select(extra_filters=extra_filters, order_by=order_by, **filters)
        )
        return dto, stmt

    def _rows_sync(self, dto: type | None, stmt: Select, *, first: bool) -> _list[DTOT]:
        """Execute a read and build every DTO it yields, projected or hydrated."""
        session = self._sync_session()
        if dto is not None:
            result = session.execute(stmt)
            rows = [result.first()] if first else result.all()
            return [dto(*row) for row in rows if row is not None]
        scalars = session.scalars(stmt)
        models = [scalars.first()] if first else scalars.all()
        return [self._hydrate_one_sync(model) for model in models if model is not None]

    def _first_sync(self, dto: type | None, stmt: Select) -> DTOT | None:
        values = self._rows_sync(dto, stmt, first=True)
        return values[0] if values else None

    def _all_sync(self, dto: type | None, stmt: Select) -> _list[DTOT]:
        return self._rows_sync(dto, stmt, first=False)

    async def _rows_async(self, dto: type | None, stmt: Select, *, first: bool) -> _list[DTOT]:
        """Await a read and build every DTO it yields, projected or hydrated."""
        result = await self._async_session().execute(stmt)
        if dto is not None:
            rows = [result.first()] if first else result.all()
            return [dto(*row) for row in rows if row is not None]
        scalars = result.scalars()
        models = [scalars.first()] if first else scalars.all()
        return [await self._hydrate_one_async(model) for model in models if model is not None]

    async def _first_async(self, dto: type | None, stmt: Select) -> DTOT | None:
        values = await self._rows_async(dto, stmt, first=True)
        return values[0] if values else None

    async def _all_async(self, dto: type | None, stmt: Select) -> _list[DTOT]:
        return await self._rows_async(dto, stmt, first=False)

    async def get[AsyncSessionT: AsyncRepositorySession](
        self: "ReadOnlyRepository[ModelT, DTOT, PKT, AsyncSessionT]", id: PKT
    ) -> DTOT | None:
        """
        Fetch one record by primary key through ``AsyncSession``.

        Returns ``None`` when no matching row exists. Await this method only on
        a repository created with ``AsyncSession``.
        """
        return await self.first(extra_filters=[self._pk_col == id])

    def get_sync(self: "ReadOnlyRepository[ModelT, DTOT, PKT, Session]", id: PKT) -> DTOT | None:
        """
        Fetch one record by primary key through ``Session``.

        Returns ``None`` when no matching row exists. This is the synchronous
        counterpart to :meth:`get`.
        """
        return self.first_sync(extra_filters=[self._pk_col == id])

    async def first[AsyncSessionT: AsyncRepositorySession](
        self: "ReadOnlyRepository[ModelT, DTOT, PKT, AsyncSessionT]",
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> DTOT | None:
        """Await the first record matching equality and expression filters."""
        dto, stmt = self._read_stmt(extra_filters=extra_filters, order_by=order_by, filters=filters)
        return await self._first_async(dto, stmt)

    def first_sync(
        self: "ReadOnlyRepository[ModelT, DTOT, PKT, Session]",
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> DTOT | None:
        """Return the first record matching equality and expression filters."""
        dto, stmt = self._read_stmt(extra_filters=extra_filters, order_by=order_by, filters=filters)
        return self._first_sync(dto, stmt)

    async def list[AsyncSessionT: AsyncRepositorySession](
        self: "ReadOnlyRepository[ModelT, DTOT, PKT, AsyncSessionT]",
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> _list[DTOT]:
        """Await all records matching equality and expression filters."""
        dto, stmt = self._read_stmt(extra_filters=extra_filters, order_by=order_by, filters=filters)
        return await self._all_async(dto, stmt)

    def list_sync(
        self: "ReadOnlyRepository[ModelT, DTOT, PKT, Session]",
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> _list[DTOT]:
        """Return all records matching equality and expression filters."""
        dto, stmt = self._read_stmt(extra_filters=extra_filters, order_by=order_by, filters=filters)
        return self._all_sync(dto, stmt)

    def _paginated_stmt(
        self,
        offset: int,
        limit: int,
        *,
        extra_filters: _list[ColumnElement[bool]] | None,
        order_by: OrderBy,
        filters: dict[str, FilterValue],
    ) -> tuple[type | None, Select, Select]:
        if order_by is None:
            raise ValueError(
                "list_paginated requires order_by: pagination is unstable without a stable order"
            )
        dto, stmt = self._read_stmt(extra_filters=extra_filters, order_by=order_by, filters=filters)
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        return dto, stmt.offset(offset).limit(limit), count_stmt

    async def list_paginated[AsyncSessionT: AsyncRepositorySession](
        self: "ReadOnlyRepository[ModelT, DTOT, PKT, AsyncSessionT]",
        offset: int,
        limit: int = 20,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> PaginatedResult[DTOT]:
        """
        Await one ordered page and its total matching-row count.

        ``order_by`` is required because offset pagination has no stable meaning
        without an explicit order.
        """
        dto, stmt, count_stmt = self._paginated_stmt(
            offset, limit, extra_filters=extra_filters, order_by=order_by, filters=filters
        )
        session = self._async_session()
        total = await session.scalar(count_stmt) or 0
        items = await self._all_async(dto, stmt)
        return PaginatedResult(items=items, total=total)

    def list_paginated_sync(
        self: "ReadOnlyRepository[ModelT, DTOT, PKT, Session]",
        offset: int,
        limit: int = 20,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> PaginatedResult[DTOT]:
        """Return one ordered page and its total matching-row count."""
        dto, stmt, count_stmt = self._paginated_stmt(
            offset, limit, extra_filters=extra_filters, order_by=order_by, filters=filters
        )
        total = self._sync_session().scalar(count_stmt) or 0
        items = self._all_sync(dto, stmt)
        return PaginatedResult(items=items, total=total)

    async def count[AsyncSessionT: AsyncRepositorySession](
        self: "ReadOnlyRepository[ModelT, DTOT, PKT, AsyncSessionT]",
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        **filters: FilterValue,
    ) -> int:
        """Await the count of rows matching the supplied filters."""
        stmt = self._apply_filters(select(self._pk_col), extra_filters=extra_filters, **filters)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        return await self._async_session().scalar(count_stmt) or 0

    def count_sync(
        self: "ReadOnlyRepository[ModelT, DTOT, PKT, Session]",
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        **filters: FilterValue,
    ) -> int:
        """Return the count of rows matching the supplied filters."""
        stmt = self._apply_filters(select(self._pk_col), extra_filters=extra_filters, **filters)
        return self._sync_session().scalar(select(func.count()).select_from(stmt.subquery())) or 0

    async def exists[AsyncSessionT: AsyncRepositorySession](
        self: "ReadOnlyRepository[ModelT, DTOT, PKT, AsyncSessionT]", id: PKT
    ) -> bool:
        """Await whether a primary-key row exists."""
        stmt = select(self._pk_col).where(self._pk_col == id).limit(1)
        return await self._async_session().scalar(stmt) is not None

    def exists_sync(self: "ReadOnlyRepository[ModelT, DTOT, PKT, Session]", id: PKT) -> bool:
        """Return whether a primary-key row exists."""
        stmt = select(self._pk_col).where(self._pk_col == id).limit(1)
        return self._sync_session().scalar(stmt) is not None


class Repository[
    ModelT,
    DTOT = ModelT,
    CreateT = object,
    UpdateT = object,
    PKT = int,
    SessionT: RepositorySession = Session,
](ReadOnlyRepository[ModelT, DTOT, PKT, SessionT]):
    """CRUD repository with async methods and explicit ``*_sync`` counterparts."""

    def _model_from_payload(self, payload: CreateT) -> ModelT:
        if not is_dataclass(payload):
            raise TypeError("Create payload must be a dataclass instance")
        kwargs = {
            field.name: getattr(payload, field.name)
            for field in fields(payload)
            if hasattr(self.model_class, field.name)
            and not isinstance(getattr(payload, field.name), UnsetType)
        }
        return self.model_class(**kwargs)

    async def _get_model_async(self, id: PKT) -> ModelT | None:
        result = await self._async_session().execute(
            select(self.model_class).where(self._pk_col == id)
        )
        return result.scalars().first()

    def _get_model_sync(self, id: PKT) -> ModelT | None:
        stmt = select(self.model_class).where(self._pk_col == id)
        return self._sync_session().scalars(stmt).first()

    async def create[AsyncSessionT: AsyncRepositorySession](
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, AsyncSessionT]",
        payload: CreateT,
        *,
        commit: bool | None = None,
    ) -> PKT:
        """
        Insert ``payload``, flush it, and return its primary key.

        ``UNSET`` payload fields are omitted. ``commit`` overrides the
        repository's ``autocommit`` setting for this operation only.
        """
        session = self._async_session()
        model = self._model_from_payload(payload)
        await self._emit_async("create", "before", model, payload)
        session.add(model)
        await self._flush_async()
        await self._emit_async("create", "after", model)
        pk = self._model_pk(model)
        await self._commit_async(commit)
        return pk

    def create_sync(
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, Session]",
        payload: CreateT,
        *,
        commit: bool | None = None,
    ) -> PKT:
        """Synchronously insert ``payload``, flush it, and return its primary key."""
        session = self._sync_session()
        model = self._model_from_payload(payload)
        self._emit_sync("create", "before", model, payload)
        session.add(model)
        self._flush_sync()
        self._emit_sync("create", "after", model)
        pk = self._model_pk(model)
        self._commit_sync(commit)
        return pk

    @staticmethod
    def _apply_payload(model: ModelT, payload: UpdateT) -> None:
        if not is_dataclass(payload):
            raise TypeError("Update payload must be a dataclass instance")
        for field in fields(payload):
            value = getattr(payload, field.name)
            if not isinstance(value, UnsetType) and hasattr(model, field.name):
                setattr(model, field.name, value)

    def _model_pk(self, model: ModelT) -> PKT:
        return cast("PKT", getattr(model, self._pk_col.key))

    async def update[AsyncSessionT: AsyncRepositorySession](
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, AsyncSessionT]",
        id: PKT,
        payload: UpdateT,
        *,
        commit: bool | None = None,
    ) -> bool:
        """Apply non-``UNSET`` payload fields and report whether the row existed."""
        model = await self._get_model_async(id)
        if model is None:
            return False
        self._apply_payload(model, payload)
        await self._emit_async("update", "before", model, payload)
        await self._flush_async()
        await self._emit_async("update", "after", model)
        await self._commit_async(commit)
        return True

    def update_sync(
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, Session]",
        id: PKT,
        payload: UpdateT,
        *,
        commit: bool | None = None,
    ) -> bool:
        """Synchronously apply non-``UNSET`` payload fields."""
        model = self._get_model_sync(id)
        if model is None:
            return False
        self._apply_payload(model, payload)
        self._emit_sync("update", "before", model, payload)
        self._flush_sync()
        self._emit_sync("update", "after", model)
        self._commit_sync(commit)
        return True

    async def delete[AsyncSessionT: AsyncRepositorySession](
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, AsyncSessionT]",
        id: PKT,
        *,
        commit: bool | None = None,
    ) -> bool:
        """Delete one row and report whether it existed."""
        session = self._async_session()
        model = await self._get_model_async(id)
        if model is None:
            return False
        await self._emit_async("delete", "before", model)
        await session.delete(model)
        await self._flush_async()
        await self._emit_async("delete", "after", model)
        await self._commit_async(commit)
        return True

    def delete_sync(
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, Session]",
        id: PKT,
        *,
        commit: bool | None = None,
    ) -> bool:
        """Synchronously delete one row and report whether it existed."""
        session = self._sync_session()
        model = self._get_model_sync(id)
        if model is None:
            return False
        self._emit_sync("delete", "before", model)
        session.delete(model)
        self._flush_sync()
        self._emit_sync("delete", "after", model)
        self._commit_sync(commit)
        return True

    async def bulk_create[AsyncSessionT: AsyncRepositorySession](
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, AsyncSessionT]",
        payloads: _list[CreateT],
        *,
        hooks: bool = False,
        commit: bool | None = None,
    ) -> _list[PKT]:
        """
        Insert payloads in one flush and return primary keys in input order.

        Set ``hooks=True`` to run create hooks for every payload. The default
        uses the faster set-based path and skips those hooks.
        """
        session = self._async_session()
        models = [self._model_from_payload(payload) for payload in payloads]
        if hooks:
            for model, payload in zip(models, payloads, strict=True):
                await self._emit_async("create", "before", model, payload)
        session.add_all(models)
        await self._flush_async()
        if hooks:
            for model in models:
                await self._emit_async("create", "after", model)
        await self._commit_async(commit)
        return [self._model_pk(model) for model in models]

    def bulk_create_sync(
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, Session]",
        payloads: _list[CreateT],
        *,
        hooks: bool = False,
        commit: bool | None = None,
    ) -> _list[PKT]:
        """Synchronously insert payloads in one flush and return their keys."""
        session = self._sync_session()
        models = [self._model_from_payload(payload) for payload in payloads]
        if hooks:
            for model, payload in zip(models, payloads, strict=True):
                self._emit_sync("create", "before", model, payload)
        session.add_all(models)
        self._flush_sync()
        if hooks:
            for model in models:
                self._emit_sync("create", "after", model)
        self._commit_sync(commit)
        return [self._model_pk(model) for model in models]

    def _update_where_stmt(
        self, extra_filters: tuple[ColumnElement[bool], ...], values: dict[str, object]
    ) -> Update:
        if not extra_filters:
            raise ValueError(
                "update_where requires at least one filter (refusing a full-table update)"
            )
        mapper = inspect(self.model_class)
        if not isinstance(mapper, Mapper):
            raise TypeError(f"Could not inspect mapper for {self.model_class.__name__}")
        for key in values:
            if key not in mapper.columns:
                raise ValueError(
                    f"update_where: '{key}' is not a column of {self.model_class.__name__}"
                )
        return (
            update(self.model_class)
            .where(*extra_filters)
            .values(**values)
            .execution_options(synchronize_session=False)
        )

    async def update_where[AsyncSessionT: AsyncRepositorySession](
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, AsyncSessionT]",
        *extra_filters: ColumnElement[bool],
        commit: bool | None = None,
        **values: object,
    ) -> int:
        """Await a guarded set-based update and return its affected-row count."""
        stmt = self._update_where_stmt(extra_filters, values)
        result = await self._run_async(lambda: self._async_session().execute(stmt))
        await self._commit_async(commit)
        return self._affected_row_count(result)

    def update_where_sync(
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, Session]",
        *extra_filters: ColumnElement[bool],
        commit: bool | None = None,
        **values: object,
    ) -> int:
        """Synchronously run a guarded set-based update."""
        stmt = self._update_where_stmt(extra_filters, values)
        result = self._run_sync(lambda: self._sync_session().execute(stmt))
        self._commit_sync(commit)
        return self._affected_row_count(result)

    def _delete_where_stmt(
        self, extra_filters: tuple[ColumnElement[bool], ...], filters: dict[str, FilterValue]
    ) -> Delete:
        if not extra_filters and not filters:
            raise ValueError(
                "delete_where requires at least one filter (refusing a full-table delete)"
            )
        return (
            delete(self.model_class)
            .where(*self._filter_clauses(**filters), *extra_filters)
            .execution_options(synchronize_session=False)
        )

    @staticmethod
    def _affected_row_count(result: object) -> int:
        if not isinstance(result, CursorResult):
            raise TypeError("Expected a cursor result from a write statement")
        return result.rowcount or 0

    async def delete_where[AsyncSessionT: AsyncRepositorySession](
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, AsyncSessionT]",
        *extra_filters: ColumnElement[bool],
        commit: bool | None = None,
        **filters: FilterValue,
    ) -> int:
        """Await a guarded set-based delete and return its affected-row count."""
        stmt = self._delete_where_stmt(extra_filters, filters)
        result = await self._run_async(lambda: self._async_session().execute(stmt))
        await self._commit_async(commit)
        return self._affected_row_count(result)

    def delete_where_sync(
        self: "Repository[ModelT, DTOT, CreateT, UpdateT, PKT, Session]",
        *extra_filters: ColumnElement[bool],
        commit: bool | None = None,
        **filters: FilterValue,
    ) -> int:
        """Synchronously run a guarded set-based delete."""
        stmt = self._delete_where_stmt(extra_filters, filters)
        result = self._run_sync(lambda: self._sync_session().execute(stmt))
        self._commit_sync(commit)
        return self._affected_row_count(result)
