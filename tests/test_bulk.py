import pytest
from conftest import User, UserCreate, UserRepo
from sqlalchemy import select
from sqlalchemy.orm import Session

from repositron import on


def _fetch(session: Session, uid: int) -> User:
    row = session.get(User, uid)
    assert row is not None
    return row


def test_bulk_create_returns_pks_in_order(session: Session):
    ids = UserRepo(session).bulk_create(
        [UserCreate(name="Ada"), UserCreate(name="Linus"), UserCreate(name="Grace")]
    )
    assert len(ids) == 3
    assert all(isinstance(i, int) for i in ids)
    names = [_fetch(session, i).name for i in ids]
    assert names == ["Ada", "Linus", "Grace"]


def test_bulk_create_empty_is_noop(session: Session):
    assert UserRepo(session).bulk_create([]) == []


def test_bulk_create_omits_unset(session: Session):
    (uid,) = UserRepo(session).bulk_create([UserCreate(name="Ada")])  # is_active UNSET
    assert _fetch(session, uid).is_active is True  # column default applied


def test_bulk_create_skips_hooks_by_default(session: Session):
    fired: list[str] = []

    class HookedRepo(UserRepo):
        @on("create", mode="before")
        def _mark(self, model, payload):
            fired.append(model.name)

    HookedRepo(session).bulk_create([UserCreate(name="Ada")])
    assert fired == []


def test_bulk_create_fires_hooks_when_asked(session: Session):
    fired: list[str] = []

    class HookedRepo(UserRepo):
        @on("create", mode="before")
        def _mark(self, model, payload):
            fired.append(model.name)

    HookedRepo(session).bulk_create([UserCreate(name="Ada"), UserCreate(name="Linus")], hooks=True)
    assert fired == ["Ada", "Linus"]


def test_update_where_returns_rowcount(session: Session, seed_users):
    repo = UserRepo(session)
    n = repo.update_where(User.is_active.is_(True), is_active=False)
    assert n == 2  # Ada + Grace were active
    assert session.scalars(select(User).where(User.is_active.is_(True))).all() == []


def test_update_where_refuses_full_table(session: Session):
    with pytest.raises(ValueError, match="requires at least one filter"):
        UserRepo(session).update_where(is_active=False)


def test_delete_where_returns_rowcount(session: Session, seed_users):
    repo = UserRepo(session)
    n = repo.delete_where(User.is_active.is_(False))
    assert n == 1  # only Linus was inactive
    assert session.get(User, seed_users[0].id) is not None  # Ada survives


def test_delete_where_refuses_full_table(session: Session):
    with pytest.raises(ValueError, match="requires at least one filter"):
        UserRepo(session).delete_where()
