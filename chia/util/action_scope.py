from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Dict, Generic, List, Optional, Protocol, Type, TypeVar

import aiosqlite

from chia.util.db_wrapper import DBWrapper2, execute_fetchone


class ResourceManager(Protocol):
    @classmethod
    @contextlib.asynccontextmanager
    async def managed(cls, initial_resource: SideEffects) -> AsyncIterator[ResourceManager]:
        # We have to put this yield here for mypy to recognize the function as a generator
        yield  # type: ignore[misc]

    @contextlib.asynccontextmanager
    async def use(self) -> AsyncIterator[None]:
        # We have to put this yield here for mypy to recognize the function as a generator
        yield

    async def get_resource(self, resource_type: Type[_T_SideEffects]) -> _T_SideEffects: ...

    async def save_resource(self, resource: SideEffects) -> None: ...

    async def get_memos(self) -> Dict[bytes, bytes]: ...

    async def save_memos(self, memos: Dict[bytes, bytes]) -> None: ...


@dataclass
class SQLiteResourceManager:

    _db: DBWrapper2
    _active_writer: Optional[aiosqlite.Connection] = field(init=False, default=None)

    def get_active_writer(self) -> aiosqlite.Connection:
        if self._active_writer is None:
            raise RuntimeError("Can only access resources while under `use()` context manager")

        return self._active_writer

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(cls, initial_resource: SideEffects) -> AsyncIterator[ResourceManager]:
        async with DBWrapper2.managed(":memory:", reader_count=0) as db:
            self = cls(db)
            async with self._db.writer() as conn:
                await conn.execute("CREATE TABLE memos(" " key blob," " value blob" ")")
                await conn.execute("CREATE TABLE side_effects(" " total blob" ")")
                await conn.execute(
                    "INSERT INTO side_effects VALUES(?)",
                    (bytes(initial_resource),),
                )
            yield self

    @contextlib.asynccontextmanager
    async def use(self) -> AsyncIterator[None]:
        async with self._db.writer() as conn:
            self._active_writer = conn
            yield
            self._active_writer = None

    async def get_resource(self, resource_type: Type[_T_SideEffects]) -> _T_SideEffects:
        row = await execute_fetchone(self.get_active_writer(), "SELECT total FROM side_effects")
        assert row is not None
        side_effects = resource_type.from_bytes(row[0])
        return side_effects

    async def save_resource(self, resource: SideEffects) -> None:
        await self.get_active_writer().execute("DELETE FROM side_effects")
        await self.get_active_writer().execute(
            "INSERT INTO side_effects VALUES(?)",
            (bytes(resource),),
        )

    async def get_memos(self) -> Dict[bytes, bytes]:
        rows = await self.get_active_writer().execute_fetchall("SELECT key, value FROM memos")
        memos = {row[0]: row[1] for row in rows}
        return memos

    async def save_memos(self, memos: Dict[bytes, bytes]) -> None:
        await self.get_active_writer().execute("DELETE FROM memos")
        await self.get_active_writer().executemany(
            "INSERT INTO memos VALUES(?, ?)",
            memos.items(),
        )


class SideEffects(Protocol):
    def __bytes__(self) -> bytes: ...

    @classmethod
    def from_bytes(cls: Type[_T_SideEffects], blob: bytes) -> _T_SideEffects: ...


_T_SideEffects = TypeVar("_T_SideEffects", bound=SideEffects)


@dataclass
class ActionScope(Generic[_T_SideEffects]):
    """
    The idea of a wallet action is to map a single user input to many potentially distributed wallet functions and side
    effects. The eventual goal is to have this be the only connection between a wallet type and the WSM.

    Utilizes a "resource manager" to hold the state in order to take advantage of rollbacks and prevent concurrent tasks
    from interferring with each other.
    """

    _resource_manager: ResourceManager
    _side_effects_format: Type[_T_SideEffects]
    _callbacks: List[Callable[[StateInterface[_T_SideEffects]], Awaitable[None]]] = field(default_factory=list)
    _final_side_effects: Optional[_T_SideEffects] = field(init=False, default=None)

    @property
    def side_effects(self) -> _T_SideEffects:
        if self._final_side_effects is None:
            raise RuntimeError(
                "Can only request ActionScope.side_effects after exiting context manager. "
                "While in context manager, use ActionScope.use()."
            )

        return self._final_side_effects

    @classmethod
    @contextlib.asynccontextmanager
    async def new_scope(
        cls,
        side_effects_format: Type[_T_SideEffects],
        resource_manager_backend: Type[ResourceManager] = SQLiteResourceManager,
    ) -> AsyncIterator[ActionScope[_T_SideEffects]]:
        async with resource_manager_backend.managed(side_effects_format()) as resource_manager:
            self = cls(_resource_manager=resource_manager, _side_effects_format=side_effects_format)
            try:
                yield self
            except Exception:
                raise
            else:
                async with self.use(_callbacks_allowed=False) as interface:
                    for callback in self._callbacks:
                        await callback(interface)
                    self._final_side_effects = interface.side_effects

    @contextlib.asynccontextmanager
    async def use(self, _callbacks_allowed: bool = True) -> AsyncIterator[StateInterface[_T_SideEffects]]:
        async with self._resource_manager.use():
            memos = await self._resource_manager.get_memos()
            side_effects = await self._resource_manager.get_resource(self._side_effects_format)
            interface = StateInterface(memos, side_effects, _callbacks_allowed)
            yield interface
            await self._resource_manager.save_memos(interface.memos)
            await self._resource_manager.save_resource(interface.side_effects)
            self._callbacks.extend(interface._new_callbacks)


@dataclass
class StateInterface(Generic[_T_SideEffects]):
    memos: Dict[bytes, bytes]
    side_effects: _T_SideEffects
    _callbacks_allowed: bool
    _new_callbacks: List[Callable[[StateInterface[_T_SideEffects]], Awaitable[None]]] = field(default_factory=list)

    def add_callback(self, callback: Callable[[StateInterface[_T_SideEffects]], Awaitable[None]]) -> None:
        if not self._callbacks_allowed:
            raise ValueError("Cannot create a new callback from within another callback")
        self._new_callbacks.append(callback)
