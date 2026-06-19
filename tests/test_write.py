import pytest
from conftest import User, UserCreate, UserRepo, UserUpdate
from sqlalchemy import select
from sqlalchemy.orm import Session

from repositron import UNSET, PrimaryKey


def _fetch(session: Session, uid: PrimaryKey) -> User:
    row = session.get(User, uid)
    assert row is not None
    return row


def test_create_returns_new_pk(session: Session):
    new_id = UserRepo(session).create(UserCreate(name="Ada", email="ada@example.com"))
    assert isinstance(new_id, int)
    assert session.get(User, new_id) is not None


def test_create_omits_unset_so_default_applies(session: Session):
    # is_active left UNSET -> the model/column default (True) applies
    new_id = UserRepo(session).create(UserCreate(name="Ada"))
    assert _fetch(session, new_id).is_active is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (UNSET, "ada@example.com"),  # update: UNSET leaves the existing value
        (None, None),  # update: None writes NULL
        ("new@example.com", "new@example.com"),  # update: real value writes through
    ],
)
def test_update_unset_vs_none_semantics(session: Session, value, expected):
    repo = UserRepo(session)
    uid = repo.create(UserCreate(name="Ada", email="ada@example.com"))
    repo.update(uid, UserUpdate(email=value))
    assert _fetch(session, uid).email == expected


def test_create_unset_vs_none(session: Session):
    repo = UserRepo(session)
    default_id = repo.create(UserCreate(name="A", email=UNSET))  # default None
    null_id = repo.create(UserCreate(name="B", email=None))  # explicit NULL
    assert _fetch(session, default_id).email is None
    assert _fetch(session, null_id).email is None


def test_update_returns_false_when_absent(session: Session):
    assert UserRepo(session).update(99999, UserUpdate(name="x")) is False


def test_delete_returns_true_then_false(session: Session):
    repo = UserRepo(session)
    uid = repo.create(UserCreate(name="Ada"))
    assert repo.delete(uid) is True
    assert repo.delete(uid) is False


def test_writes_flush_but_do_not_commit(session: Session):
    repo = UserRepo(session)
    repo.create(UserCreate(name="Ephemeral"))
    # visible in-session after flush
    assert session.scalar(select(User).where(User.name == "Ephemeral")) is not None
    # but a rollback discards it -> the repo never committed
    session.rollback()
    assert session.scalar(select(User).where(User.name == "Ephemeral")) is None
