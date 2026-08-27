"""AsyncSession coverage for the unified repository API."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

import pytest
from conftest import Base, User, UserCreate, UserDTO, UserNarrow, UserRepo, UserUpdate
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_scoped_session,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session

from repositron import Repository, on, writes


class AsyncUserRepo(Repository[User, UserDTO, UserCreate, UserUpdate, int, AsyncSession]):
    """The regular repository API, bound to an AsyncSession for type checking."""


class ScopedUserRepo(
    Repository[User, UserDTO, UserCreate, UserUpdate, int, async_scoped_session[AsyncSession]]
):
    """The same API bound to SQLAlchemy's task-local async session proxy."""


async def _with_session[ResultT](
    operation: Callable[[AsyncSession], Awaitable[ResultT]],
) -> ResultT:
    """Create an isolated in-memory async database and run one operation."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            return await operation(session)
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


def test_async_crud_projection_pagination_and_bulk_write() -> None:
    async def operation(session: AsyncSession) -> None:
        repo = AsyncUserRepo(session)
        ada_id = await repo.create(UserCreate(name="Ada", age=36))
        linus_id = await repo.create(UserCreate(name="Linus", age=54))

        assert await repo.count() == 2
        assert await repo.exists(ada_id) is True
        assert await repo.get(999) is None
        assert await repo[UserNarrow].get(ada_id) == UserNarrow(id=ada_id, name="Ada")

        page = await repo.list_paginated(0, 1, order_by=User.id)
        assert page.total == 2
        assert page.items == [UserDTO(ada_id, "Ada", None, 36, True)]

        assert await repo.update(linus_id, UserUpdate(name="Linus T.")) is True
        updated = await repo.get(linus_id)
        assert updated is not None and updated.name == "Linus T."
        assert await repo.bulk_create([UserCreate(name="Grace")])
        assert await repo.delete(ada_id) is True

    asyncio.run(_with_session(operation))


def test_async_hooks_and_writes() -> None:
    async def operation(session: AsyncSession) -> None:
        events: list[str] = []

        class HookedRepo(AsyncUserRepo):
            @on("create", mode="before")
            async def stamp(self, model, payload) -> None:
                await asyncio.sleep(0)
                model.email = f"{model.name}@example.test"
                events.append("before")

            @on("create", mode="after")
            def capture(self, model) -> None:
                events.append(f"after:{model.id}")

            @writes
            async def rename(self, id: int, name: str) -> str:
                user = await self.session.get(User, id)
                assert user is not None
                user.name = name
                return user.name

        repo = HookedRepo(session)
        user_id = await repo.create(UserCreate(name="Ada"))
        assert events == ["before", f"after:{user_id}"]
        created = await repo.get(user_id)
        assert created is not None and created.email == "Ada@example.test"
        assert await repo.rename(user_id, "Ada Lovelace") == "Ada Lovelace"
        renamed = await repo.get(user_id)
        assert renamed is not None and renamed.name == "Ada Lovelace"

    asyncio.run(_with_session(operation))


def test_async_scoped_session_is_supported() -> None:
    async def operation(session: AsyncSession) -> None:
        factory = async_sessionmaker(session.bind, expire_on_commit=False)
        scoped = async_scoped_session(factory, scopefunc=asyncio.current_task)
        try:
            repo = ScopedUserRepo(scoped)
            user_id = await repo.create(UserCreate(name="Ada"))
            user = await repo.get(user_id)
            assert user is not None and user.name == "Ada"
        finally:
            await scoped.remove()

    asyncio.run(_with_session(operation))


def test_wrong_mode_has_a_clear_error(session: Session) -> None:
    sync_repo = UserRepo(session)
    async_get = cast("Callable[[int], Awaitable[object]]", sync_repo.get)

    async def call_async_api() -> None:
        await async_get(1)

    with pytest.raises(TypeError, match=r"\*_sync"):
        asyncio.run(call_async_api())

    async def call_sync_api(async_session: AsyncSession) -> None:
        sync_get = cast("Callable[[int], object]", AsyncUserRepo(async_session).get_sync)
        with pytest.raises(TypeError, match="awaited repository method"):
            sync_get(1)

    asyncio.run(_with_session(call_sync_api))
