import pytest
from conftest import Account, AccountRepo, User, UserDTO, UserRepo
from sqlalchemy.orm import Session

from repositron import UNSET, Repository, UnsetType


def test_type_args_resolved_from_orig_bases(session: Session):
    repo = UserRepo(session)
    assert repo.model_class is User
    assert repo.dto_class is UserDTO


def test_dto_omitted_falls_back_to_model(session: Session):
    class ModelRepo(Repository[User]):
        pass

    assert ModelRepo(session).dto_class is User


def test_unparameterized_repo_raises_type_error(session: Session):
    class Bare(Repository):
        pass

    with pytest.raises(TypeError, match="must be parameterized"):
        _ = Bare(session).model_class


def test_custom_pk_column_used(session: Session, seed_accounts: list[Account]):
    repo = AccountRepo(session)
    aid = seed_accounts[0].account_id
    assert repo.get(aid) is not None  # keyed by account_id, not id
    assert repo.exists(aid) is True
    assert repo.exists("missing") is False


def test_bad_pk_column_raises(session: Session):
    class WrongPK(Repository[User]):
        pk_column = "nope"

    with pytest.raises(AttributeError, match="nope"):
        WrongPK(session).get(1)


def test_empty_dto_projection_raises(session: Session, seed_users: list[User]):
    from dataclasses import dataclass

    @dataclass
    class Empty:
        pass

    with pytest.raises(ValueError, match="no fields"):
        UserRepo(session)[Empty].list(order_by=User.id)


def test_dto_field_maps_to_no_column_raises(session: Session, seed_users: list[User]):
    from dataclasses import dataclass

    @dataclass
    class Bogus:
        ghost: int

    with pytest.raises(AttributeError, match="maps to no column"):
        UserRepo(session)[Bogus].list(order_by=User.id)


def test_unset_singleton_identity():
    assert UnsetType() is UNSET  # identity comparison is load-bearing
