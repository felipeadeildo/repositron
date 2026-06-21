from conftest import (
    Account,
    AccountNarrow,
    AccountRepo,
    User,
    UserNarrow,
    UserRepo,
)
from sqlalchemy.orm import Session


def _select_columns(sql_log: list[str]) -> str:
    """Return the column segment (between SELECT and FROM) of the last SELECT emitted."""
    select = next(s for s in reversed(sql_log) if s.lstrip().upper().startswith("SELECT"))
    upper = select.upper()
    # FROM may be preceded by a space or a newline in the compiled statement.
    from_at = min(i for i in (upper.find(" FROM"), upper.find("\nFROM")) if i != -1)
    return select[:from_at].lower()


def test_narrow_dto_projects_only_its_columns(
    session: Session, sql_log: list[str], seed_users: list[User]
):
    repo = UserRepo(session)
    sql_log.clear()
    repo[UserNarrow].list(order_by=User.id)
    cols = _select_columns(sql_log)
    assert "id" in cols and "name" in cols
    assert "email" not in cols and "age" not in cols and "is_active" not in cols


def test_full_dto_loads_all_columns(session: Session, sql_log: list[str], seed_users: list[User]):
    # contrapositive: without projection the whole row is loaded
    repo = UserRepo(session)  # default DTO is the full UserDTO -> hydration, no projection
    sql_log.clear()
    repo.list(order_by=User.id)
    cols = _select_columns(sql_log)
    assert "email" in cols and "age" in cols and "is_active" in cols


def test_projection_builds_dto_positionally_with_field_mapping(
    session: Session, seed_accounts: list[Account]
):
    # AccountNarrow fields (account_id, rank); `rank` maps to model column mention_rank.
    rows = AccountRepo(session)[AccountNarrow].list(order_by=Account.mention_rank.desc())
    assert all(isinstance(r, AccountNarrow) for r in rows)
    assert rows[0].rank == 3  # right value in the right slot


def test_projection_applies_to_first_and_paginated(
    session: Session, sql_log: list[str], seed_users: list[User]
):
    repo = UserRepo(session)

    sql_log.clear()
    repo[UserNarrow].first(order_by=User.id)
    assert "email" not in _select_columns(sql_log)

    sql_log.clear()
    page = repo[UserNarrow].list_paginated(0, 10, order_by=User.id)
    assert "email" not in _select_columns(sql_log)
    assert all(isinstance(i, UserNarrow) for i in page.items)


def test_get_projects_when_shape_bound(
    session: Session, sql_log: list[str], seed_users: list[User]
):
    repo = UserRepo(session)
    uid = seed_users[0].id

    sql_log.clear()
    narrow = repo[UserNarrow].get(uid)
    assert isinstance(narrow, UserNarrow)
    assert "email" not in _select_columns(sql_log)  # projected, like first/list

    full = repo.get(uid)  # no shape bound -> full DTO, hydrated
    assert full is not None
    assert full.email == "ada@example.com"


def test_non_dataclass_dto_does_not_project(
    session: Session, sql_log: list[str], seed_users: list[User]
):
    # default DTO is a dataclass here, so use a UserDTO repo (full) which still hydrates,
    # and confirm the full-column load (already covered) by checking the model-as-dto path.
    from repositron import Repository

    class ModelRepo(Repository[User]):
        pass

    sql_log.clear()
    ModelRepo(session).list(order_by=User.id)
    cols = _select_columns(sql_log)
    assert "email" in cols  # model-as-DTO: no projection, whole row


def test_default_dataclass_dto_with_derived_field_hydrates(
    session: Session, seed_users: list[User]
):
    # A default DTO may carry a field no column backs, populated in _hydrate. Reads
    # without repo[Shape] must hydrate, not project (which would fail on that field).
    from dataclasses import dataclass, field

    from repositron import Repository

    @dataclass
    class UserWithRoles:
        id: int
        name: str
        roles: list[str] = field(default_factory=list)  # derived, not a column

    class RoleRepo(Repository[User, UserWithRoles]):
        def _hydrate(self, model: User) -> UserWithRoles:
            return UserWithRoles(id=model.id, name=model.name, roles=["admin"])

    repo = RoleRepo(session)
    assert repo.list(order_by=User.id)[0].roles == ["admin"]

    first = repo.first(order_by=User.id)
    assert first is not None and first.roles == ["admin"]

    got = repo.get(seed_users[0].id)
    assert got is not None and got.roles == ["admin"]
