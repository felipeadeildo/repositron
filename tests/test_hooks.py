from dataclasses import dataclass, replace

import pytest
from conftest import User, UserCreate, UserNarrow, UserUpdate
from sqlalchemy.orm import Session

from repositron import Repository, on


@dataclass(frozen=True, slots=True)
class UserTagged:
    id: int
    name: str
    tag: str = ""  # derived, not a column; filled by a hydrate hook


def test_before_create_mutates_model(session: Session):
    class Repo(Repository[User, User, UserCreate, UserUpdate]):
        @on("create", mode="before")
        def stamp(self, model, payload):
            model.email = f"{model.name}@hook.test"

    uid = Repo(session).create(UserCreate(name="Ada"))
    row = session.get(User, uid)
    assert row is not None and row.email == "Ada@hook.test"


def test_after_create_sees_pk(session: Session):
    seen = {}

    class Repo(Repository[User, User, UserCreate, UserUpdate]):
        @on("create", mode="after")
        def capture(self, model):
            seen["id"] = model.id  # populated only after flush

    uid = Repo(session).create(UserCreate(name="Ada"))
    assert seen["id"] == uid


def test_update_and_delete_hooks_fire(session: Session):
    events = []

    class Repo(Repository[User, User, UserCreate, UserUpdate]):
        @on("update", mode="before")
        def u_before(self, model, payload):
            events.append("u_before")

        @on("update", mode="after")
        def u_after(self, model):
            events.append("u_after")

        @on("delete", mode="before")
        def d_before(self, model):
            events.append("d_before")

        @on("delete", mode="after")
        def d_after(self, model):
            events.append("d_after")

    repo = Repo(session)
    uid = repo.create(UserCreate(name="Ada"))
    repo.update(uid, UserUpdate(name="Ada L."))
    repo.delete(uid)
    assert events == ["u_before", "u_after", "d_before", "d_after"]


def test_hydrate_after_enriches_dto(session: Session):
    class Repo(Repository[User, UserTagged]):
        @on("hydrate", mode="after")
        def tag(self, model, dto):
            return replace(dto, tag=f"u{model.id}")

    repo = Repo(session)
    user = User(name="Ada")
    session.add(user)
    session.flush()
    got = repo.get(user.id)
    assert got is not None and got.tag == f"u{user.id}"
    assert repo.list()[0].tag == f"u{user.id}"


def test_projection_skips_hydrate_hooks(session: Session, seed_users: list[User]):
    # A hydrate hook would crash on a narrow shape (no `tag` field). Projection must
    # not run it: repo[UserNarrow] returns the shape untouched.
    class Repo(Repository[User, UserTagged]):
        @on("hydrate", mode="after")
        def tag(self, model, dto):
            return replace(dto, tag="x")

    rows = Repo(session)[UserNarrow].list(order_by=User.id)
    assert all(isinstance(r, UserNarrow) for r in rows)  # built, no hook crash


def test_hooks_compose_across_mixins_in_order(session: Session):
    order = []

    class StampMixin:
        @on("create", mode="before")
        def base_stamp(self, model, payload):
            order.append("mixin")

    class Repo(StampMixin, Repository[User, User, UserCreate, UserUpdate]):
        @on("create", mode="before")
        def own_stamp(self, model, payload):
            order.append("own")

    Repo(session).create(UserCreate(name="Ada"))
    assert order == ["mixin", "own"]  # base-to-subclass


def test_stacked_on_runs_for_each_event(session: Session):
    fired = []

    class Repo(Repository[User, User, UserCreate, UserUpdate]):
        @on("create", mode="after")
        @on("update", mode="after")
        def touch(self, model):
            fired.append(model.id)

    repo = Repo(session)
    uid = repo.create(UserCreate(name="Ada"))
    repo.update(uid, UserUpdate(name="Ada L."))
    assert fired == [uid, uid]


def test_unknown_hook_raises_at_class_definition():
    with pytest.raises(TypeError, match="unknown hook"):

        class Repo(Repository[User, User, UserCreate, UserUpdate]):
            @on("create", mode="during")  # type: ignore[ty:invalid-argument-type]
            def bad(self, model, payload): ...
