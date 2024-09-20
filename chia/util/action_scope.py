from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Generic, Optional, Protocol, Type, TypeVar, final

import aiosqlite

from chia.util.db_wrapper import DBWrapper2, execute_fetchone


class ResourceManager(Protocol):
    @classmethod
    @contextlib.asynccontextmanager
    async def managed(cls, initial_resource: SideEffects) -> AsyncIterator[ResourceManager]:  # pragma: no cover
        # yield included to make this a generator as expected by @contextlib.asynccontextmanager
        yield  # type: ignore[misc]

    @contextlib.asynccontextmanager
    async def use(self) -> AsyncIterator[None]:  # pragma: no cover
        # yield included to make this a generator as expected by @contextlib.asynccontextmanager
        yield

    async def get_resource(self, resource_type: Type[_T_SideEffects]) -> _T_SideEffects: ...

    async def save_resource(self, resource: SideEffects) -> None: ...


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
                await conn.execute("CREATE TABLE side_effects(total blob)")
                await conn.execute(
                    "INSERT INTO side_effects VALUES(?)",
                    (bytes(initial_resource),),
                )
            yield self

    @contextlib.asynccontextmanager
    async def use(self) -> AsyncIterator[None]:
        if self._active_writer is not None:
            raise RuntimeError("SQLiteResourceManager cannot currently support nested transactions")
        async with self._db.writer() as conn:
            self._active_writer = conn
            try:
                yield
            finally:
                self._active_writer = None

    async def get_resource(self, resource_type: Type[_T_SideEffects]) -> _T_SideEffects:
        row = await execute_fetchone(self.get_active_writer(), "SELECT total FROM side_effects")
        assert row is not None
        side_effects = resource_type.from_bytes(row[0])
        return side_effects

    async def save_resource(self, resource: SideEffects) -> None:
        # This sets all rows (there's only one) to the new serialization
        await self.get_active_writer().execute(
            "UPDATE side_effects SET total=?",
            (bytes(resource),),
        )


class SideEffects(Protocol):
    def __bytes__(self) -> bytes: ...

    @classmethod
    def from_bytes(cls: Type[_T_SideEffects], blob: bytes) -> _T_SideEffects: ...


_T_SideEffects = TypeVar("_T_SideEffects", bound=SideEffects)
_T_Config = TypeVar("_T_Config")


@final
@dataclass
class ActionScope(Generic[_T_SideEffects, _T_Config]):
    """
    The idea of an "action" is to map a single client input to many potentially distributed functions and side
    effects. The action holds on to a temporary state that the many callers modify at will but only one at a time.
    When the action is closed, the state is still available and can be committed elsewhere or discarded.

    Utilizes a "resource manager" to hold the state in order to take advantage of rollbacks and prevent concurrent tasks
    from interfering with each other.
    """

    _resource_manager: ResourceManager
    _side_effects_format: Type[_T_SideEffects]
    _config: _T_Config  # An object not intended to be mutated during the lifetime of the scope
    _callback: Optional[Callable[[StateInterface[_T_SideEffects]], Awaitable[None]]] = None
    _final_side_effects: Optional[_T_SideEffects] = field(init=False, default=None)

    @property
    def side_effects(self) -> _T_SideEffects:
        if self._final_side_effects is None:
            raise RuntimeError(
                "Can only request ActionScope.side_effects after exiting context manager. "
                "While in context manager, use ActionScope.use()."
            )

        return self._final_side_effects

    @property
    def config(self) -> _T_Config:
        return self._config

    @classmethod
    @contextlib.asynccontextmanager
    async def new_scope(
        cls,
        side_effects_format: Type[_T_SideEffects],
        # I want a default here in case a use case doesn't want to take advantage of the config but no default seems to
        # satisfy the type hint _T_Config so we'll just ignore this.
        config: _T_Config = object(),  # type: ignore[assignment]
        resource_manager_backend: Type[ResourceManager] = SQLiteResourceManager,
    ) -> AsyncIterator[ActionScope[_T_SideEffects, _T_Config]]:
        async with resource_manager_backend.managed(side_effects_format()) as resource_manager:
            self = cls(_resource_manager=resource_manager, _side_effects_format=side_effects_format, _config=config)

            yield self

            async with self.use(_callbacks_allowed=False) as interface:
                if self._callback is not None:
                    await self._callback(interface)
                self._final_side_effects = interface.side_effects

    @contextlib.asynccontextmanager
    async def use(self, _callbacks_allowed: bool = True) -> AsyncIterator[StateInterface[_T_SideEffects]]:
        async with self._resource_manager.use():
            side_effects = await self._resource_manager.get_resource(self._side_effects_format)
            interface = StateInterface(side_effects, _callbacks_allowed, self._callback)

            yield interface

            await self._resource_manager.save_resource(interface.side_effects)
            self._callback = interface.callback


@dataclass
class StateInterface(Generic[_T_SideEffects]):
    side_effects: _T_SideEffects
    _callbacks_allowed: bool
    _callback: Optional[Callable[[StateInterface[_T_SideEffects]], Awaitable[None]]] = None

    @property
    def callback(self) -> Optional[Callable[[StateInterface[_T_SideEffects]], Awaitable[None]]]:
        return self._callback

    def set_callback(self, new_callback: Optional[Callable[[StateInterface[_T_SideEffects]], Awaitable[None]]]) -> None:
        if not self._callbacks_allowed:
            raise RuntimeError("Callback cannot be edited from inside itself")

        self._callback = new_callback
