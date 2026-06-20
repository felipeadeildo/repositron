import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import ClassVar

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from repositron import UNSET, ReadOnlyRepository, Repository, UnsetType


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str | None] = mapped_column(default=None)
    age: Mapped[int | None] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(default=True)


class Account(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(primary_key=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    name: Mapped[str]
    mention_rank: Mapped[int | None] = mapped_column(default=None)


# --- DTOs / payloads ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UserDTO:
    id: int
    name: str
    email: str | None
    age: int | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class UserNarrow:  # the projection star: only id + name
    id: int
    name: str


@dataclass
class UserCreate:
    name: str
    email: str | None | UnsetType = UNSET
    age: int | None | UnsetType = UNSET
    is_active: bool | UnsetType = UNSET


@dataclass
class UserUpdate:
    name: str | UnsetType = UNSET
    email: str | None | UnsetType = UNSET
    age: int | None | UnsetType = UNSET


@dataclass(frozen=True, slots=True)
class AccountDTO:
    account_id: str
    name: str
    rank: int | None  # renamed from model column `mention_rank`


@dataclass(frozen=True, slots=True)
class AccountNarrow:
    account_id: str
    rank: int | None


# --- repositories ------------------------------------------------------------


# PKT left to default (int): User.id is an int key.
class UserRepo(Repository[User, UserDTO, UserCreate, UserUpdate]):
    pass


# Full CRUD with a str key: PKT=str in the 5th slot, pk_column as a string name.
class AccountRepo(Repository[Account, AccountDTO, object, object, str]):
    pk_column = "account_id"
    field_mapping: ClassVar[dict[str, str]] = {"mention_rank": "rank"}


# pk_column as a column reference, PKT typed str so get/exists are checked against str.
class AccountReadRepo(ReadOnlyRepository[Account, AccountDTO, str]):
    pk_column = Account.account_id
    field_mapping: ClassVar[dict[str, str]] = {"mention_rank": "rank"}


# --- fixtures ----------------------------------------------------------------


@pytest.fixture(scope="session")
def engine() -> Engine:
    return create_engine("sqlite://")


@pytest.fixture(scope="session", autouse=True)
def _schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    # Wrap each test in a transaction we roll back, so tests stay isolated without
    # re-creating tables. Mirrors the library's "caller owns the transaction" contract.
    conn = engine.connect()
    txn = conn.begin()
    s = Session(bind=conn)
    yield s
    s.close()
    if txn.is_active:  # a test may roll back itself (e.g. proving no commit happened)
        txn.rollback()
    conn.close()


@pytest.fixture
def sql_log(engine: Engine) -> Iterator[list[str]]:
    """Record every SQL statement emitted, so tests can assert on the projected columns."""
    stmts: list[str] = []

    def record(conn, cursor, statement, params, context, executemany):
        stmts.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    yield stmts
    event.remove(engine, "before_cursor_execute", record)


@pytest.fixture
def seed_users(session: Session) -> list[User]:
    users = [
        User(name="Ada", email="ada@example.com", age=36, is_active=True),
        User(name="Linus", email=None, age=54, is_active=False),
        User(name="Grace", email="grace@example.com", age=85, is_active=True),
    ]
    session.add_all(users)
    session.flush()
    return users


@pytest.fixture
def seed_accounts(session: Session) -> list[Account]:
    accounts = [
        Account(account_id=str(uuid.uuid4()), owner_id=uuid.uuid4(), name="Acme", mention_rank=3),
        Account(account_id=str(uuid.uuid4()), name="Globex", mention_rank=None),
    ]
    session.add_all(accounts)
    session.flush()
    return accounts
