"""
repositron: a typed, generic SQLAlchemy 2.0 repository base.

Declare a Model (and optionally a DTO and write payloads), inherit one generic
base, and get a typed repository with filtering, ordering, pagination, column
projection, and model-to-DTO hydration, without per-table CRUD boilerplate.

    from repositron import Repository, UNSET, UnsetType

    class TargetRepository(Repository[Target, TargetDTO, TargetCreate, TargetUpdate]):
        field_mapping = {"mention_rank": "rank"}
"""

from repositron.base import OrderBy, PaginatedResult
from repositron.hooks import on, writes
from repositron.sentinel import UNSET, UnsetType
from repositron.sql import ReadOnlyRepository, Repository

__all__ = [
    "UNSET",
    "OrderBy",
    "PaginatedResult",
    "ReadOnlyRepository",
    "Repository",
    "UnsetType",
    "on",
    "writes",
]
