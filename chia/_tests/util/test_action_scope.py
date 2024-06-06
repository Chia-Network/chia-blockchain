from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

import pytest

from chia.util.action_scope import ActionScope, StateInterface


@dataclass
class TestSideEffects:
    buf: bytes = b""

    def __bytes__(self) -> bytes:
        return self.buf

    @classmethod
    def from_bytes(cls, blob: bytes) -> TestSideEffects:
        return cls(blob)


async def default_async_callback(interface: StateInterface[TestSideEffects]) -> None:
    return None


async def default_async_commit(interface: TestSideEffects) -> None:
    return None


# Test adding a callback
def test_add_callback() -> None:
    state_interface = StateInterface({}, TestSideEffects(), True)
    initial_count = len(state_interface._new_callbacks)
    state_interface.add_callback(default_async_callback)
    assert len(state_interface._new_callbacks) == initial_count + 1


# Fixture to create an ActionScope with a mocked DBWrapper2
@pytest.fixture
async def action_scope() -> AsyncIterator[ActionScope[TestSideEffects]]:
    async with ActionScope.new_scope(TestSideEffects) as scope:
        yield scope


# Test creating a new ActionScope and ensuring tables are created
@pytest.mark.anyio
async def test_new_action_scope(action_scope: ActionScope[TestSideEffects]) -> None:
    async with action_scope.use() as interface:
        assert interface == StateInterface({}, TestSideEffects(), True)


@pytest.mark.anyio
async def test_scope_persistence(action_scope: ActionScope[TestSideEffects]) -> None:
    async with action_scope.use() as interface:
        interface.memos[b"foo"] = b"bar"
        interface.side_effects.buf = b"bar"

    async with action_scope.use() as interface:
        assert interface.memos[b"foo"] == b"bar"
        assert interface.side_effects.buf == b"bar"


@pytest.mark.anyio
async def test_transactionality(action_scope: ActionScope[TestSideEffects]) -> None:
    async with action_scope.use() as interface:
        interface.memos[b"foo"] = b"bar"
        interface.side_effects.buf = b"bar"

    try:
        async with action_scope.use() as interface:
            interface.memos[b"foo"] = b"qux"
            interface.side_effects.buf = b"qat"
            raise RuntimeError("Going to be caught")
    except RuntimeError:
        pass

    async with action_scope.use() as interface:
        assert interface.memos[b"foo"] == b"bar"
        assert interface.side_effects.buf == b"bar"


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
    try:
        async with ActionScope.new_scope(TestSideEffects) as action_scope:
            async with action_scope.use() as interface:

                async def callback(interface: StateInterface[TestSideEffects]) -> None:
                    raise NotImplementedError("Should not get here")  # pragma: no cover

                interface.add_callback(callback)

            async with action_scope.use() as interface:
                raise RuntimeError("This should prevent the callbacks from being called")
    except RuntimeError:
        pass
