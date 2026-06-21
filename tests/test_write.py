import pytest
from conftest import User, UserCreate, UserRepo, UserUpdate
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.orm import Session

from repositron import UNSET, Repository, writes


def _fetch(session: Session, uid: int) -> User:
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


def test_autocommit_instance_survives_rollback(session: Session):
    repo = UserRepo(session, autocommit=True)
    repo.create(UserCreate(name="Durable"))
    session.rollback()  # nothing to undo: the create already committed
    assert session.scalar(select(User).where(User.name == "Durable")) is not None


def test_commit_override_true_on_flush_only_repo(session: Session):
    repo = UserRepo(session)  # autocommit off
    repo.create(UserCreate(name="Forced"), commit=True)
    session.rollback()
    assert session.scalar(select(User).where(User.name == "Forced")) is not None


def test_commit_override_false_on_autocommit_repo(session: Session):
    repo = UserRepo(session, autocommit=True)
    repo.create(UserCreate(name="Held"), commit=False)  # override off
    session.rollback()
    assert session.scalar(select(User).where(User.name == "Held")) is None


# name is NOT NULL; nulling it forces an IntegrityError at flush. The UserUpdate
# field is typed str|UNSET (None is not a valid value), so the checker is told to
# allow this one deliberately-invalid payload.
_NULL_NAME = UserUpdate(name=None)  # type: ignore[ty:invalid-argument-type]


def test_flush_error_rolls_back_by_default(session: Session):
    repo = UserRepo(session)
    uid = repo.create(UserCreate(name="Ada"))
    with pytest.raises(IntegrityError):
        repo.update(uid, _NULL_NAME)
    # default rollback_on_error left the session usable (not pending); the
    # rollback reverted the whole uncommitted transaction, the create included
    assert session.get(User, uid) is None


def test_flush_error_leaves_session_pending_when_disabled(session: Session):
    repo = UserRepo(session, rollback_on_error=False)
    uid = repo.create(UserCreate(name="Ada"))
    with pytest.raises(IntegrityError):
        repo.update(uid, _NULL_NAME)
    # no rollback happened: the session is stuck until the caller rolls back
    with pytest.raises(PendingRollbackError):
        session.scalar(select(User))


# --- @writes -----------------------------------------------------------------


class WriteRepo(Repository[User, User, UserCreate, UserUpdate]):
    @writes
    def add_named(self, name: str) -> int:
        """Custom write WITHOUT a commit kwarg. Flushes itself to read the pk back."""
        user = User(name=name)
        self.session.add(user)
        self.session.flush()  # the method flushes when it needs the assigned pk
        return user.id

    @writes
    def add_named_committable(self, name: str, *, commit: bool | None = None) -> int:
        """Declares `commit` so the per-call override type-checks; the wrapper consumes it."""
        user = User(name=name)
        self.session.add(user)
        self.session.flush()
        return user.id


def test_writes_flushes_and_returns_value(session: Session):
    repo = WriteRepo(session)
    uid = repo.add_named("Ada")
    assert isinstance(uid, int)  # pk assigned
    assert session.scalar(select(User).where(User.name == "Ada")) is not None
    session.rollback()  # not committed
    assert session.scalar(select(User).where(User.name == "Ada")) is None


def test_writes_honors_commit_kwarg(session: Session):
    repo = WriteRepo(session)  # autocommit off
    repo.add_named_committable("Forced", commit=True)
    session.rollback()
    assert session.scalar(select(User).where(User.name == "Forced")) is not None


def test_writes_honors_autocommit(session: Session):
    repo = WriteRepo(session, autocommit=True)
    repo.add_named("Durable")  # no commit kwarg, but autocommit is on
    session.rollback()
    assert session.scalar(select(User).where(User.name == "Durable")) is not None


def test_writes_rolls_back_on_error(session: Session):
    class BoomRepo(Repository[User, User, UserCreate, UserUpdate]):
        @writes
        def bad(self) -> None:
            self.session.add(User(name=None))  # NOT NULL violation at flush

    repo = BoomRepo(session)
    with pytest.raises(IntegrityError):
        repo.bad()
    # default rollback_on_error left the session usable
    assert session.scalar(select(User)) is None
