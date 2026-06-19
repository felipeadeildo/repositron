import pytest
from conftest import User, UserRepo
from sqlalchemy.orm import Session

from repositron import UNSET


def test_equality_and_extra_filters_combine(session: Session, seed_users: list[User]):
    rows = UserRepo(session).list(is_active=True, extra_filters=[User.age > 40])
    assert {r.name for r in rows} == {"Grace"}  # Ada is active but 36; Linus is 54 but inactive


def test_none_filter_is_is_null(session: Session, seed_users: list[User]):
    rows = UserRepo(session).list(email=None)
    assert {r.name for r in rows} == {"Linus"}


def test_unset_filter_is_skipped(session: Session, seed_users: list[User]):
    # email=UNSET must not filter anything -> all three rows
    rows = UserRepo(session).list(email=UNSET)
    assert len(rows) == 3


def test_invalid_filter_key_raises(session: Session, seed_users: list[User]):
    with pytest.raises(ValueError, match="no attribute"):
        UserRepo(session).list(nonexistent=1)


def test_list_paginated_requires_order_by(session: Session, seed_users: list[User]):
    with pytest.raises(ValueError, match="order_by"):
        UserRepo(session).list_paginated(0, 10)


def test_list_paginated_total_vs_items(session: Session, seed_users: list[User]):
    page = UserRepo(session).list_paginated(0, 2, order_by=User.id)
    assert len(page.items) == 2  # page respects limit
    assert page.total == 3  # total ignores offset/limit
