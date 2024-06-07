from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, final

import pytest

from chia.util.action_scope import ActionScope, StateInterface


@final
@dataclass
class TestSideEffects:
    buf: bytes = b""

    def __bytes__(self) -> bytes:
        return self.buf

    @classmethod
    def from_bytes(cls, blob: bytes) -> TestSideEffects:
        return cls(blob)


async def default_async_callback(interface: StateInterface[TestSideEffects]) -> None:
    return None  # pragma: no cover


# Test adding a callback
def test_add_callback() -> None:
    state_interface = StateInterface(TestSideEffects(), True)
    initial_callbacks = list(state_interface._new_callbacks)
    state_interface.add_callback(default_async_callback)
    assert state_interface._new_callbacks == [*initial_callbacks, default_async_callback]
    initial_callbacks.append(default_async_callback)
    state_interface.add_callback(default_async_callback)
    assert state_interface._new_callbacks == [*initial_callbacks, default_async_callback]


@pytest.fixture(name="action_scope")
async def action_scope_fixture() -> AsyncIterator[ActionScope[TestSideEffects]]:
    async with ActionScope.new_scope(TestSideEffects) as scope:
        yield scope


@pytest.mark.anyio
async def test_new_action_scope(action_scope: ActionScope[TestSideEffects]) -> None:
    """
    Assert we can immediately check out some initial state
    """
    async with action_scope.use() as interface:
        assert interface == StateInterface(TestSideEffects(), True)


@pytest.mark.anyio
async def test_scope_persistence(action_scope: ActionScope[TestSideEffects]) -> None:
    """ """
    async with action_scope.use() as interface:
        interface.side_effects.buf = b"baz"

    async with action_scope.use() as interface:
        assert interface.side_effects.buf == b"baz"


@pytest.mark.anyio
async def test_transactionality(action_scope: ActionScope[TestSideEffects]) -> None:
    async with action_scope.use() as interface:
        interface.side_effects.buf = b"baz"

    with pytest.raises(Exception, match="Going to be caught"):
        async with action_scope.use() as interface:
            interface.side_effects.buf = b"qat"
            raise RuntimeError("Going to be caught")

    async with action_scope.use() as interface:
        assert interface.side_effects.buf == b"baz"


@pytest.mark.anyio
async def test_callbacks() -> None:
    async with ActionScope.new_scope(TestSideEffects) as action_scope:
        async with action_scope.use() as interface:

            async def callback(interface: StateInterface[TestSideEffects]) -> None:
                interface.side_effects.buf = b"bar"

            interface.add_callback(callback)

    assert action_scope.side_effects.buf == b"bar"


@pytest.mark.anyio
async def test_callback_in_callback_error() -> None:
    with pytest.raises(ValueError, match="callback"):
        async with ActionScope.new_scope(TestSideEffects) as action_scope:
            async with action_scope.use() as interface:

                async def callback(interface: StateInterface[TestSideEffects]) -> None:
                    interface.add_callback(default_async_callback)

                interface.add_callback(callback)


@pytest.mark.anyio
async def test_no_callbacks_if_error() -> None:
    with pytest.raises(Exception, match="This should prevent the callbacks from being called"):
        async with ActionScope.new_scope(TestSideEffects) as action_scope:
            async with action_scope.use() as interface:

                async def callback(interface: StateInterface[TestSideEffects]) -> None:
                    raise NotImplementedError("Should not get here")  # pragma: no cover

                interface.add_callback(callback)

            async with action_scope.use() as interface:
                raise RuntimeError("This should prevent the callbacks from being called")

    with pytest.raises(Exception, match="This should prevent the callbacks from being called"):
        async with ActionScope.new_scope(TestSideEffects) as action_scope:
            async with action_scope.use() as interface:

                async def callback(interface: StateInterface[TestSideEffects]) -> None:
                    raise NotImplementedError("Should not get here")  # pragma: no cover

                interface.add_callback(callback)

            raise RuntimeError("This should prevent the callbacks from being called")
