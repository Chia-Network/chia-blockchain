from __future__ import annotations

import contextlib
import copy
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from typing_extensions import Self

_T_SideEffects = TypeVar("_T_SideEffects")
_T_Config = TypeVar("_T_Config")


@dataclass
class ResourceManager(Generic[_T_SideEffects]):
    _side_effects: _T_SideEffects
    _active_writer: bool = False

    @classmethod
    @contextlib.asynccontextmanager
    async def managed(cls, initial_resource: _T_SideEffects) -> AsyncIterator[Self]:
        yield cls(copy.deepcopy(initial_resource))

    @contextlib.asynccontextmanager
    async def use(self) -> AsyncIterator[_T_SideEffects]:
        if self._active_writer:
            raise RuntimeError("ResourceManager cannot currently support nested transactions")
        self._active_writer = True
        side_effects_copy = copy.deepcopy(self._side_effects)
        try:
            yield side_effects_copy
        except:
            raise
        else:
            self._side_effects = copy.deepcopy(side_effects_copy)
        finally:
            self._active_writer = False


@dataclass
class ActionScope(Generic[_T_SideEffects, _T_Config]):
    """
    The idea of an "action" is to map a single client input to many potentially distributed functions and side
    effects. The action holds on to a temporary state that the many callers modify at will but only one at a time.
    When the action is closed, the state is still available and can be committed elsewhere or discarded.

    Utilizes a "resource manager" to hold the state in order to take advantage of rollbacks and prevent concurrent tasks
    from interfering with each other.
    """

    _resource_manager: ResourceManager[_T_SideEffects]
    _config: _T_Config  # An object not intended to be mutated during the lifetime of the scope
    _callback: Callable[[StateInterface[_T_SideEffects]], Awaitable[None]] | None = None
    _final_side_effects: _T_SideEffects | None = field(init=False, default=None)

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
        initial_resource: _T_SideEffects,
        # I want a default here in case a use case doesn't want to take advantage of the config but no default seems to
        # satisfy the type hint _T_Config so we'll just ignore this.
        config: _T_Config = object(),  # type: ignore[assignment]
    ) -> AsyncIterator[ActionScope[_T_SideEffects, _T_Config]]:
        async with ResourceManager.managed(initial_resource) as resource_manager:
            self = cls(_resource_manager=resource_manager, _config=config)

            try:
                yield self
            except:
                raise
            else:
                async with self.use(_callbacks_allowed=False) as interface:
                    if self._callback is not None:
                        await self._callback(interface)
                    self._final_side_effects = interface.side_effects

    @contextlib.asynccontextmanager
    async def use(self, _callbacks_allowed: bool = True) -> AsyncIterator[StateInterface[_T_SideEffects]]:
        async with self._resource_manager.use() as side_effects:
            interface = StateInterface(side_effects, _callbacks_allowed, self._callback)

            try:
                yield interface
            except:
                raise
            else:
                self._callback = interface.callback


@dataclass
class StateInterface(Generic[_T_SideEffects]):
    side_effects: _T_SideEffects
    _callbacks_allowed: bool
    _callback: Callable[[StateInterface[_T_SideEffects]], Awaitable[None]] | None = None

    @property
    def callback(self) -> Callable[[StateInterface[_T_SideEffects]], Awaitable[None]] | None:
        return self._callback

    def set_callback(self, new_callback: Callable[[StateInterface[_T_SideEffects]], Awaitable[None]] | None) -> None:
        if not self._callbacks_allowed:
            raise RuntimeError("Callback cannot be edited from inside itself")

        self._callback = new_callback
