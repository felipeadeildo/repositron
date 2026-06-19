import pytest
from conftest import Account, AccountDTO, AccountRepo, User, UserDTO
from sqlalchemy.orm import Session

from repositron import Repository


class UserModelAsDTORepo(Repository[User]):  # no DTO -> model is the DTO
    pass


class UserDataclassRepo(Repository[User, UserDTO]):
    pass


def test_model_as_dto_returns_the_model_instance(session: Session, seed_users: list[User]):
    repo = UserModelAsDTORepo(session)
    got = repo.get(seed_users[0].id)
    assert got is seed_users[0]  # identity: no hydration, the model itself


def test_dataclass_dto_built_by_field_name(session: Session, seed_users: list[User]):
    repo = UserDataclassRepo(session)
    got = repo.get(seed_users[0].id)
    assert isinstance(got, UserDTO)
    assert (got.name, got.email, got.age) == ("Ada", "ada@example.com", 36)


def test_pydantic_dto_via_model_validate(session: Session, seed_users: list[User]):
    pydantic = pytest.importorskip("pydantic")

    class UserOut(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(from_attributes=True)
        id: int
        name: str

    class PydanticRepo(Repository[User, UserOut]):
        pass

    got = PydanticRepo(session).get(seed_users[0].id)
    assert isinstance(got, UserOut)
    assert got.name == "Ada"


def test_field_mapping_renames_on_dataclass_hydration(
    session: Session, seed_accounts: list[Account]
):
    # model column `mention_rank` must land in DTO field `rank`
    got = AccountRepo(session).get(seed_accounts[0].account_id)
    assert isinstance(got, AccountDTO)
    assert got.rank == 3


def test_unsupported_dto_raises_not_implemented(session: Session, seed_users: list[User]):
    class Opaque:  # not the model, not a dataclass, no model_validate; rejects the kwargs
        def __init__(self) -> None: ...

    class OpaqueRepo(Repository[User, Opaque]):
        pass

    with pytest.raises(NotImplementedError):
        OpaqueRepo(session).get(seed_users[0].id)
