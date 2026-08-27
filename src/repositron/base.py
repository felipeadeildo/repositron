"""Shared repository types and pagination results."""

import datetime
import uuid
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession, async_scoped_session
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql.elements import ColumnElement

from repositron.sentinel import UnsetType

_list = list

type AsyncRepositorySession = AsyncSession | async_scoped_session[AsyncSession]
"""An async SQLAlchemy session or its task-local scoped proxy."""

type RepositorySession = Session | AsyncRepositorySession
"""A caller-owned SQLAlchemy session accepted by a repository."""

type OrderColumn = ColumnElement | InstrumentedAttribute
"""A model attribute or SQLAlchemy ordering expression."""

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
"""A value accepted by equality filters."""

type OrderBy = OrderColumn | _list[OrderColumn] | None
"""One ordering term, several terms, or no ordering."""


@dataclass(frozen=True, slots=True)
class PaginatedResult[DTOT]:
    """One page of records and the matching-row count without pagination."""

    items: list[DTOT]
    total: int
