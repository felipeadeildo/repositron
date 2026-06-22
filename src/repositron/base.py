"""
Backend-agnostic repository contracts and the pagination container.

These declare what a repository offers, independent of any database. The
SQLAlchemy implementation that a project actually inherits from lives in
`repositron.sql`. Import `Repository` from the package root, not from here.
"""

import datetime
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql.elements import ColumnElement

from repositron.sentinel import UnsetType

_list = list  # the list() method below shadows the builtin in class scope

type OrderColumn = ColumnElement | InstrumentedAttribute
"""A single ordering term: a model attribute (`User.id`) or an expression (`User.id.desc()`)."""

type FilterValue = (
    int
    | str
    | uuid.UUID
    | float
    | bool
    | datetime.datetime
    | datetime.date
    | Enum
    | None
    | UnsetType
)
"""The value of an equality filter. `UNSET` skips the filter; `None` filters by `IS NULL`."""

type OrderBy = OrderColumn | _list[OrderColumn] | None
"""An ordering: one column, a list of columns, or `None` for no ordering."""


@dataclass(frozen=True, slots=True)
class PaginatedResult[DTOT]:
    """One page of results plus the count the query would return unpaginated."""

    items: list[DTOT]
    total: int
    """Total matching rows ignoring offset/limit; for computing page counts."""


class ReadOnlyRepositoryABC[ModelT, DTOT = ModelT, PKT = int](ABC):
    """
    Read-only side of the repository contract (get, first, list, count, exists).

    Backends implement this; consumers inherit the concrete `ReadOnlyRepository`
    from `repositron.sql` instead.
    """

    @abstractmethod
    def get(self, id: PKT) -> DTOT | None:
        """Get a single record by primary key, or None if absent."""
        raise NotImplementedError

    @abstractmethod
    def first(
        self,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> DTOT | None:
        """Get the first record matching the filters, or None."""
        raise NotImplementedError

    @abstractmethod
    def list(
        self,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> _list[DTOT]:
        """List records matching the filters."""
        raise NotImplementedError

    @abstractmethod
    def list_paginated(
        self,
        offset: int,
        limit: int = 20,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        order_by: OrderBy = None,
        **filters: FilterValue,
    ) -> PaginatedResult[DTOT]:
        """List records with pagination. `order_by` is required."""
        raise NotImplementedError

    @abstractmethod
    def count(
        self, *, extra_filters: _list[ColumnElement[bool]] | None = None, **filters: FilterValue
    ) -> int:
        """Count records matching the filters."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, id: PKT) -> bool:
        """Check whether a record with this primary key exists."""
        raise NotImplementedError


class CRUDRepositoryABC[
    ModelT,
    DTOT = ModelT,
    CreateT = object,
    UpdateT = object,
    PKT = int,
](ReadOnlyRepositoryABC[ModelT, DTOT, PKT]):
    """Adds create/update/delete to the read-only contract."""

    @abstractmethod
    def create(self, payload: CreateT) -> PKT:
        """Create a record from a dataclass payload. Returns the new primary key."""
        raise NotImplementedError

    @abstractmethod
    def update(self, id: PKT, payload: UpdateT) -> bool:
        """Partial-update a record; UNSET fields are skipped. False if not found."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, id: PKT) -> bool:
        """Delete a record by primary key. False if not found."""
        raise NotImplementedError


class Writable(Protocol):
    """
    The transaction surface a `@writes`-decorated method relies on.

    Structural, so `@writes` accepts any repository regardless of how its
    generic parameters are bound; both `ReadOnlyRepository` and `Repository`
    satisfy it.
    """

    session: Session

    def _run[R](self, op: Callable[[], R]) -> R: ...
    def _commit(self, commit: bool | None) -> None: ...
