"""
Backend-agnostic repository contracts and the pagination container.

These declare what a repository offers, independent of any database. The
SQLAlchemy implementation that a project actually inherits from lives in
`repositron.sql`. Import `Repository` from the package root, not from here.
"""

import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.sql.elements import ColumnElement

from repositron.sentinel import UnsetType

_list = list  # the list() method below shadows the builtin in class scope

# Equality-filter value: UNSET skips the filter, None filters by IS NULL.
type FilterValue = (
    str | int | float | bool | datetime.datetime | datetime.date | Enum | None | UnsetType
)

# order_by value: a column, a list of columns, or None for no ordering.
type OrderBy = ColumnElement | _list[ColumnElement] | None


@dataclass(frozen=True, slots=True)
class PaginatedResult[DTOT]:
    """One page of results plus the count the query would return unpaginated."""

    items: list[DTOT]
    total: int
    """Total matching rows ignoring offset/limit; for computing page counts."""


class ReadOnlyRepositoryABC[ModelT, DTOT = ModelT, IdT = int](ABC):
    """
    Read-only side of the repository contract (get, first, list, count, exists).

    Backends implement this; consumers inherit the concrete `ReadOnlyRepository`
    from `repositron.sql` instead.
    """

    @abstractmethod
    def get(self, id: IdT) -> DTOT | None:
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
        self,
        *,
        extra_filters: _list[ColumnElement[bool]] | None = None,
        **filters: FilterValue,
    ) -> int:
        """Count records matching the filters."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, id: IdT) -> bool:
        """Check whether a record with this primary key exists."""
        raise NotImplementedError


class CRUDRepositoryABC[
    ModelT,
    DTOT = ModelT,
    CreateT = object,
    UpdateT = object,
    IdT = int,
](ReadOnlyRepositoryABC[ModelT, DTOT, IdT]):
    """Adds create/update/delete to the read-only contract."""

    @abstractmethod
    def create(self, payload: CreateT) -> IdT:
        """Create a record from a dataclass payload. Returns the new primary key."""
        raise NotImplementedError

    @abstractmethod
    def update(self, id: IdT, payload: UpdateT) -> bool:
        """Partial-update a record; UNSET fields are skipped. False if not found."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, id: IdT) -> bool:
        """Delete a record by primary key. False if not found."""
        raise NotImplementedError
