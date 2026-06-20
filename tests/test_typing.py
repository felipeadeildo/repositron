"""
Static-typing checks. The `assert_type` calls are verified by `ty`, not pytest: they
fail type-checking (not at runtime) if PK/DTO inference regresses. The block lives under
TYPE_CHECKING so it is never executed; `test_typing_module_imports` keeps pytest happy.
"""

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_type

from conftest import (
    Account,
    AccountDTO,
    AccountReadRepo,
    UserDTO,
    UserRepo,
)
from sqlalchemy.orm import Session

from repositron import ReadOnlyRepository, Repository

if TYPE_CHECKING:

    @dataclass
    class _UuidCreate:
        name: str

    class UuidRepo(Repository[Account, Account, _UuidCreate, object, uuid.UUID]):
        pk_column = "account_id"

    def _checks(session: Session) -> None:
        user_repo = UserRepo(session)
        # DTO and the default int key flow through to the read methods.
        assert_type(user_repo.get(1), UserDTO | None)
        assert_type(user_repo.list(), list[UserDTO])

        # str-keyed repo: PKT=str was declared, so get/exists take str.
        assert_type(AccountReadRepo(session).get("abc"), AccountDTO | None)

        # PKT in the 5th slot: create() returns it.
        assert_type(UuidRepo(session).create(_UuidCreate(name="x")), uuid.UUID)

        # repo[DTO] projection keeps the model and PKT, swaps the DTO.
        assert_type(
            AccountReadRepo(session)[AccountDTO],
            ReadOnlyRepository[Account, AccountDTO, str],
        )


def test_typing_module_imports() -> None:
    # The real assertions are static (see the TYPE_CHECKING block). This just confirms
    # the module imports cleanly so a typo doesn't silently skip type-checking.
    assert UserRepo is not None
