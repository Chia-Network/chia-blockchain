from __future__ import annotations

import contextlib
import copy
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass, field
from typing import Any, AsyncContextManager, Callable, Generic, Optional, Protocol, TypeVar, final


class SideEffects(Protocol):
    def __bytes__(self) -> bytes: ...

    @classmethod
    def from_bytes(cls: type[_T_SideEffects], blob: bytes) -> _T_SideEffects: ...


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

    _lock: Callable[..., AsyncContextManager[Any]]
    _active_interface: StateInterface[_T_SideEffects]
    _config: _T_Config  # An object not intended to be mutated during the lifetime of the scope
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
        lock: Callable[..., AsyncContextManager[Any]],
        initial_side_effects: _T_SideEffects,
        # I want a default here in case a use case doesn't want to take advantage of the config but no default seems to
        # satisfy the type hint _T_Config so we'll just ignore this.
        config: _T_Config = object(),  # type: ignore[assignment]
    ) -> AsyncIterator[ActionScope[_T_SideEffects, _T_Config]]:
        self = cls(
            _lock=lock, _active_interface=StateInterface(initial_side_effects, _callbacks_allowed=True), _config=config
        )

        yield self

        async with self.use(_callbacks_allowed=False) as interface:
            if interface.callback is not None:
                await interface.callback(interface)
            self._final_side_effects = interface.side_effects

    @contextlib.asynccontextmanager
    async def use(self, _callbacks_allowed: bool = True) -> AsyncIterator[StateInterface[_T_SideEffects]]:
        new_interface = copy.deepcopy(self._active_interface)
        previous_interface = self._active_interface

        try:
            self._active_interface = new_interface
            self._active_interface._callbacks_allowed = _callbacks_allowed
            yield self._active_interface
            self._active_interface._callbacks_allowed = previous_interface._callbacks_allowed
            for field, value in self._active_interface.__dict__.items():
                previous_interface.__dict__[field] = value
        finally:
            self._active_interface = previous_interface


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
