"""
Concrete SQLAlchemy repositories: `ReadOnlyRepository` and `Repository`.

The working classes a project inherits from. They implement the contracts in
`repositron.base` over a SQLAlchemy `Session`, adding model-to-DTO hydration,
column projection via `repo[DTO]`, and the equality/expression filter split.
"""

import copy
from collections.abc import Callable, Iterator
from dataclasses import fields, is_dataclass
from functools import cached_property
from typing import TYPE_CHECKING, ClassVar, cast, get_args, get_origin

from sqlalchemy import Select, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql.elements import ColumnElement

from repositron.base import (
    CRUDRepositoryABC,
    FilterValue,
    OrderBy,
    PaginatedResult,
    ReadOnlyRepositoryABC,
)
from repositron.hooks import HookEvent, HookMode, HookRegistry, collect_hooks, on
from repositron.sentinel import UnsetType

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

_list = list  # avoids shadowing by the list() method in class scope


class ReadOnlyRepository[ModelT, DTOT = ModelT, PKT = int](
    ReadOnlyRepositoryABC[ModelT, DTOT, PKT]
):
    """
    Typed read access to one table, parameterized by model and DTO.

    Reads return the DTO `DTOT` (defaults to `ModelT`, i.e. the model itself with
    no hydration). The instance holds no per-call state, so a single repository is
    safe to share and inject.

    Two filtering mechanisms combine in one call:

    - `**filters`: equality only (`column == value`), keyed by model attribute
      name, e.g. `name="Ale"`. `UNSET` skips that filter; `None` filters by
      `IS NULL`.
    - `extra_filters`: arbitrary SQLAlchemy expressions for what equality can't
      express, like `age > 18`, `IN`, `LIKE`, `OR`. So
      `list(name="Ale", extra_filters=[Model.age > 18])` is
      `WHERE name = 'Ale' AND age > 18`.

    The return type is resolved `repo[X]` (call site) > `DTOT` (class default) >
    `ModelT` (fallback); see `__getitem__`.
    """

    field_mapping: ClassVar[dict[str, str]] = {}
    """Renamed fields as `{model_field: dto_field}`, applied both when hydrating and when resolving projection columns."""  # noqa: E501

    pk_column: ClassVar[str | InstrumentedAttribute] = "id"
    """Primary-key column, as an attribute name (`"url_hash"`) or a column reference (`User.id`)."""

    def __init__(
        self,
        session: Session,
        *,
        autocommit: bool = False,
        rollback_on_error: bool = True,
    ) -> None:
        """
        Args:
            session: Caller-owned session. The repository never opens or closes it.
            autocommit: When True, every write commits after its flush. Default False keeps the
                transaction boundary in the caller's hands.
            rollback_on_error: When True (default), a failed flush or commit rolls the session
                back before re-raising. Set False to leave the rollback to you.

        """
        self.session = session
        self.autocommit = autocommit
        self.rollback_on_error = rollback_on_error
        self._active_dto: type | None = None
        """DTO bound via `__getitem__` (call-site override); None uses the class default."""

    _hooks: ClassVar[HookRegistry] = {}
    """Hooks declared with `@on`, collected per subclass; see `__init_subclass__`."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        # Collect @on-tagged methods once, at class definition, across the MRO.
        super().__init_subclass__(**kwargs)
        cls._hooks = collect_hooks(cls)

    def _hooks_for(self, event: HookEvent, mode: HookMode) -> Iterator[Callable]:
        """Yield the bound hook methods for `event`/`mode`, in registration order."""
        for name in self._hooks.get((event, mode), ()):
            yield getattr(self, name)

    def _emit(self, event: HookEvent, mode: HookMode, *args: object) -> None:
        """Run each hook for `event`/`mode` as a side effect, ignoring returns."""
        for hook in self._hooks_for(event, mode):
            hook(*args)

    def _flush(self) -> None:
        self._run(self.session.flush)

    def _commit(self, commit: bool | None) -> None:
        """Commit if `commit` is True, or None and `autocommit` is on."""
        if commit if commit is not None else self.autocommit:
            self._run(self.session.commit)

    def _run[R](self, op: Callable[[], R]) -> R:
        """Run `op`, rolling back on error when `rollback_on_error` is set, and return its result."""  # noqa: E501
        try:
            return op()
        except Exception:
            if self.rollback_on_error:
                self.session.rollback()
            raise

    @classmethod
    def _extract_type_arg(cls, index: int) -> type | None:
        """
        Extract a generic type argument from `__orig_bases__`, or None if absent.

        Scans for the base parameterized off `ReadOnlyRepository` and
        returns its argument at `index`. Robust to multiple inheritance (mixins
        are skipped) and to base position in the MRO. Returns None when the
        argument was omitted (e.g. DTOT left to its default) so callers can fall
        back rather than crash.
        """
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base) or base
            if isinstance(origin, type) and issubclass(origin, ReadOnlyRepository):
                args = get_args(base)
                if len(args) > index:
                    arg = args[index]
                    # A still-unbound TypeVar (default not supplied) is not a real type.
                    return arg if isinstance(arg, type) else None
                return None
        raise TypeError(
            f"Cannot infer type arguments for {cls.__name__}. Inherit passing the generic "
            f"parameters, e.g. class MyRepo(Repository[Model, DTO, Create, Update])."
        )

    @cached_property
    def model_class(self) -> type[ModelT]:
        """SQLAlchemy model class, inferred from the `ModelT` generic parameter."""
        model = self._extract_type_arg(0)
        if model is None:
            raise TypeError(f"{type(self).__name__} must be parameterized with a model class.")
        return cast("type[ModelT]", model)

    @cached_property
    def dto_class(self) -> type[DTOT]:
        """DTO class: the `DTOT` generic if supplied, else `ModelT` (model-as-DTO)."""
        dto = self._extract_type_arg(1)
        return cast("type[DTOT]", dto if dto is not None else self.model_class)

    @property
    def _dto(self) -> type:
        """Active DTO: the call-site override (`repo[X]`) if set, else the class default."""
        return self._active_dto if self._active_dto is not None else self.dto_class

    def __getitem__[S](self, dto: type[S]) -> "ReadOnlyRepository[ModelT, S, PKT]":
        """
        Return a lightweight clone bound to `dto` for this call.

        The clone shares this repository's session and diverges only in its active
        DTO, so the injected instance stays untouched and thread-safe. A narrow
        dataclass DTO triggers column projection (loads only its fields).

        Example:
            repo[TargetIdOrg].list(is_active=True)  # SELECT id, organization_id

        """
        clone = copy.copy(self)
        clone._active_dto = dto
        return cast("ReadOnlyRepository[ModelT, S, PKT]", clone)

    @cached_property
    def _pk_col(self) -> InstrumentedAttribute:
        """The primary-key column, resolved from `pk_column` (a name or a column reference)."""
        # Read pk_column off the class: a column reference is a descriptor, and instance
        # access (self.pk_column) would fire it against this unmapped repo and raise.
        pk = type(self).pk_column
        # Resolve by name through the model either way, so a column reference is validated
        # to belong to this model (a foreign column would otherwise build a cartesian query).
        name = pk if isinstance(pk, str) else pk.key
        col = getattr(self.model_class, name, None)
        if col is None:
            raise AttributeError(f"{self.model_class.__name__} has no column '{name}'")
        return col

    def _project_columns(self, dto: type) -> _list[ColumnElement]:
        """Resolve a dataclass DTO's fields to model columns (in field order), honoring field_mapping."""  # noqa: E501
        reverse = {v: k for k, v in self.field_mapping.items()}
        names = [f.name for f in fields(cast("type[DataclassInstance]", dto))]
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

    def _project(
        self,
        dto: type,
        *,
        extra_filters: _list[ColumnElement[bool]] | None,
        order_by: OrderBy,
        **filters: FilterValue,
    ) -> Select:
        """Build the column-projection statement for a dataclass `dto` (rows in field order)."""
        return self._select(
            *self._project_columns(dto),
            extra_filters=extra_filters,
            order_by=order_by,
            **filters,
        )

    @on("hydrate", mode="build")
    def _hydrate(self, model: ModelT) -> DTOT:
        """
        Build the DTO from a model. The default works for a Pydantic or dataclass
        DTO (and the model itself), honoring `field_mapping` for renames.

        Customize it when your DTO is none of those, e.g. a bare `str`. Either
        override this method, or tag your own with `@on("hydrate", mode="build")`:

            def _hydrate(self, model) -> str:
                return str(model.image)
        """
        dto = self._dto
        if dto is self.model_class:
            return cast("DTOT", model)

        try:
            # ponytail: duck-type on model_validate instead of importing pydantic, so it
            # stays a genuinely optional extra. from_attributes reads off the model; aliases rename.
            validate = getattr(dto, "model_validate", None)
            if validate is not None:
                return cast("DTOT", validate(model))

            model_dict = {k: v for k, v in model.__dict__.items() if not k.startswith("_")}
            if is_dataclass(dto):
                reverse = {v: k for k, v in self.field_mapping.items()}
                kwargs = {
                    f.name: model_dict[reverse.get(f.name, f.name)]
                    for f in fields(dto)
                    if reverse.get(f.name, f.name) in model_dict
                }
                return cast("DTOT", dto(**kwargs))
            return cast("DTOT", dto(**model_dict))
        except (AttributeError, TypeError, IndexError) as e:
            raise NotImplementedError(
                f"Cannot automatically convert {type(model).__name__} to {dto.__name__}. "
                f"Override _hydrate() in your repository subclass. Error: {e}"
            ) from e

    @cached_property
    def _build_hook(self) -> Callable[[ModelT], DTOT]:
        # The build hook, or _hydrate directly when the base is used unsubclassed.
        return next(self._hooks_for("hydrate", "build"), self._hydrate)

    @cached_property
    def _after_hooks(self) -> _list[Callable[[ModelT, DTOT], DTOT]]:
        return list(self._hooks_for("hydrate", "after"))

    def _hydrate_one(self, model: ModelT) -> DTOT:
        # Build the DTO, then let each after-hook enrich it. Projection bypasses this.
        dto = self._build_hook(model)
        for hook in self._after_hooks:
            dto = cast("DTOT", hook(model, dto))
        return dto

    def _apply_filters(
        self,
        stmt: Select,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        **filters: FilterValue,
    ) -> Select:
        """
        Apply equality `**filters` and arbitrary `extra_filters` (see class docstring).

        Raises:
            ValueError: if a `**filters` key is not a model attribute.

        """
        for key, value in filters.items():
            if isinstance(value, UnsetType):
                continue
            if not hasattr(self.model_class, key):
                raise ValueError(f"{self.model_class.__name__} has no attribute '{key}'")
            stmt = stmt.where(getattr(self.model_class, key) == value)
        if extra_filters:
            stmt = stmt.where(*extra_filters)
        return stmt

    def _apply_order(self, stmt: Select, order_by: OrderBy = None) -> Select:
        """Apply `order_by` to a statement; `None` leaves it unordered."""
        if order_by is None:
            return stmt
        if isinstance(order_by, list):
            return stmt.order_by(*order_by)
        return stmt.order_by(order_by)

    def _select(
        self,
        *columns: ColumnElement,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> Select:
        """Build a SELECT (over `columns`, or the whole model if none) with filters and order applied."""  # noqa: E501
        stmt = select(*columns) if columns else select(self.model_class)
        stmt = self._apply_filters(stmt, extra_filters=extra_filters, **filters)
        return self._apply_order(stmt, order_by=order_by)

    def _projecting(self) -> type | None:
        """
        The shape to column-project, or None to hydrate the full DTO instead.

        Projection narrows the SELECT to a shape's fields, so it only applies to a
        shape bound for the call via `repo[Shape]`. The default DTO always hydrates,
        which lets it carry fields no column backs (those `_hydrate` derives).
        """
        shape = self._active_dto
        if shape is None or shape is self.model_class:
            return None
        return shape if is_dataclass(shape) else None

    def get(self, id: PKT) -> DTOT | None:
        """Fetch one record by primary key, as the active DTO, or None if absent."""
        return self.first(extra_filters=[self._pk_col == id])

    def first(
        self,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> DTOT | None:
        """Fetch the first matching record, hydrated to the active DTO, or None."""
        dto = self._projecting()
        if dto is not None:
            stmt = self._project(dto, extra_filters=extra_filters, order_by=order_by, **filters)
            row = self.session.execute(stmt).first()
            return cast("DTOT", dto(*row)) if row is not None else None
        stmt = self._select(extra_filters=extra_filters, order_by=order_by, **filters)
        model = self.session.scalars(stmt).first()
        if model is None:
            return None
        return self._hydrate_one(model)

    def list(
        self,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> _list[DTOT]:
        """List records matching the filters, each hydrated to the active DTO."""
        dto = self._projecting()
        if dto is not None:
            stmt = self._project(dto, extra_filters=extra_filters, order_by=order_by, **filters)
            rows = self.session.execute(stmt).all()
            # Rows come back in the DTO's field order (see _project_columns); build positionally.
            return cast("_list[DTOT]", [dto(*row) for row in rows])
        stmt = self._select(extra_filters=extra_filters, order_by=order_by, **filters)
        return [self._hydrate_one(m) for m in self.session.scalars(stmt).all()]

    def list_paginated(
        self,
        offset: int,
        limit: int = 20,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> PaginatedResult[DTOT]:
        """
        Return a page of records plus the unpaginated total.

        Args:
            order_by: Required. Pagination over an unstable order silently drops
                and repeats rows across pages, so a None order is rejected.

        Raises:
            ValueError: If `order_by` is None.

        """
        if order_by is None:
            raise ValueError(
                "list_paginated requires order_by: pagination is unstable without a stable order"
            )
        dto = self._projecting()
        if dto is not None:
            stmt = self._project(dto, extra_filters=extra_filters, order_by=order_by, **filters)
            total = self._count_stmt(stmt)
            rows = self.session.execute(stmt.offset(offset).limit(limit)).all()
            items = cast("_list[DTOT]", [dto(*row) for row in rows])
            return PaginatedResult(items=items, total=total)
        stmt = self._select(extra_filters=extra_filters, order_by=order_by, **filters)
        total = self._count_stmt(stmt)
        models = self.session.scalars(stmt.offset(offset).limit(limit)).all()
        return PaginatedResult(items=[self._hydrate_one(m) for m in models], total=total)

    def _count_stmt(self, stmt: Select) -> int:
        """Total rows the statement would return, ignoring its order/offset/limit."""
        # Wrap the filtered statement as a subquery so the count is correct through
        # joins, DISTINCT, or column projection; drop ORDER BY since it can't appear
        # under COUNT without being selected.
        subq = stmt.order_by(None).subquery()
        return self.session.scalar(select(func.count()).select_from(subq)) or 0

    def count(
        self,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        **filters: FilterValue,
    ) -> int:
        """Count records matching the filters."""
        stmt = self._apply_filters(select(self._pk_col), extra_filters=extra_filters, **filters)
        return self._count_stmt(stmt)

    def exists(self, id: PKT) -> bool:
        """Check whether a record with this primary key exists."""
        stmt = select(self._pk_col).where(self._pk_col == id).limit(1)
        return self.session.scalar(stmt) is not None


class Repository[ModelT, DTOT = ModelT, CreateT = object, UpdateT = object, PKT = int](
    ReadOnlyRepository[ModelT, DTOT, PKT], CRUDRepositoryABC[ModelT, DTOT, CreateT, UpdateT, PKT]
):
    """
    Read access plus `create`/`update`/`delete` from dataclass payloads.

    Writes `flush` so the caller still owns the transaction boundary. Set
    `autocommit=True` on the instance, or pass `commit=True` on a single write,
    to commit too. `CreateT`/`UpdateT` are the payload dataclasses; `UNSET`
    fields are skipped on write.

        class UserRepository(Repository[User, UserDTO, UserCreate, UserUpdate]):
            field_mapping = {"full_name": "name"}

    Methods tagged with `@on` run inside the matching operation. Each event
    passes a fixed set of arguments; `hydrate` hooks return the DTO, the rest
    return nothing:

        ("create", "before")    (model, payload)   before the insert flushes
        ("create", "after")     (model)            after flush, key assigned
        ("update", "before")    (model, payload)   after the payload is applied
        ("update", "after")     (model)            after flush
        ("delete", "before")    (model)            before the row is deleted
        ("delete", "after")     (model)            after flush
        ("hydrate", "build")    (model)            builds the DTO (replaces the default)
        ("hydrate", "after")    (model, dto)       enriches the built DTO, on every read

    For a custom write method that isn't a plain create/update/delete, wrap it
    with `@writes` to get the same flush/commit/rollback.
    """

    def _get_model(self, id: PKT) -> ModelT | None:
        """Load the mapped instance by primary key, for an in-place update or delete."""
        stmt = select(self.model_class).where(self._pk_col == id)
        return self.session.scalars(stmt).first()

    def create(self, payload: CreateT, *, commit: bool | None = None) -> PKT:
        """
        Insert a record from a dataclass payload and flush.

        UNSET fields are omitted, so the column or model default applies.
        `commit` overrides `autocommit` for this call.

        Returns:
            The new primary-key value, read back after the flush.

        """
        kwargs = {
            f.name: getattr(payload, f.name)
            for f in fields(cast("DataclassInstance", payload))
            if hasattr(self.model_class, f.name)
            and not isinstance(getattr(payload, f.name), UnsetType)
        }
        model = self.model_class(**kwargs)
        self._emit("create", "before", model, payload)
        self.session.add(model)
        self._flush()
        self._emit("create", "after", model)
        pk = getattr(model, self._pk_col.key)
        self._commit(commit)
        return pk

    def update(self, id: PKT, payload: UpdateT, *, commit: bool | None = None) -> bool:
        """
        Apply a partial update from a dataclass payload and flush.

        UNSET fields are left untouched; `None` is written as a real value
        (SET NULL). `commit` overrides `autocommit` for this call.

        Returns:
            True on success, False if no record has that primary key.

        """
        model = self._get_model(id)
        if model is None:
            return False
        for f in fields(cast("DataclassInstance", payload)):
            value = getattr(payload, f.name)
            if not isinstance(value, UnsetType) and hasattr(model, f.name):
                setattr(model, f.name, value)
        self._emit("update", "before", model, payload)
        self._flush()
        self._emit("update", "after", model)
        self._commit(commit)
        return True

    def delete(self, id: PKT, *, commit: bool | None = None) -> bool:
        """
        Delete a record by primary key and flush.
        `commit` overrides `autocommit` for this call.

        Returns:
            True on success, False if no record has that primary key.

        """
        model = self._get_model(id)
        if model is None:
            return False
        self._emit("delete", "before", model)
        self.session.delete(model)
        self._flush()
        self._emit("delete", "after", model)
        self._commit(commit)
        return True
