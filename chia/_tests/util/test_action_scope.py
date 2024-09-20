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


@final
@dataclass
class TestConfig:
    test_foo: str = "test_foo"


async def default_async_callback(interface: StateInterface[TestSideEffects]) -> None:
    return None  # pragma: no cover


# Test adding a callback
def test_set_callback() -> None:
    state_interface = StateInterface(TestSideEffects(), True)
    state_interface.set_callback(default_async_callback)
    assert state_interface._callback is default_async_callback
    state_interface_no_callbacks = StateInterface(TestSideEffects(), False)
    with pytest.raises(RuntimeError, match="Callback cannot be edited from inside itself"):
        state_interface_no_callbacks.set_callback(None)


@pytest.fixture(name="action_scope")
async def action_scope_fixture() -> AsyncIterator[ActionScope[TestSideEffects, TestConfig]]:
    async with ActionScope.new_scope(TestSideEffects, TestConfig()) as scope:
        assert scope.config == TestConfig(test_foo="test_foo")
        yield scope


@pytest.mark.anyio
async def test_new_action_scope(action_scope: ActionScope[TestSideEffects, TestConfig]) -> None:
    """
    Assert we can immediately check out some initial state
    """
    async with action_scope.use() as interface:
        assert interface == StateInterface(TestSideEffects(), True)


@pytest.mark.anyio
async def test_scope_persistence(action_scope: ActionScope[TestSideEffects, TestConfig]) -> None:
    async with action_scope.use() as interface:
        interface.side_effects.buf = b"baz"

    async with action_scope.use() as interface:
        assert interface.side_effects.buf == b"baz"


@pytest.mark.anyio
async def test_transactionality(action_scope: ActionScope[TestSideEffects, TestConfig]) -> None:
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
    async with ActionScope.new_scope(TestSideEffects, TestConfig()) as action_scope:
        async with action_scope.use() as interface:

            async def callback(interface: StateInterface[TestSideEffects]) -> None:
                interface.side_effects.buf = b"bar"

            interface.set_callback(callback)

        async with action_scope.use():
            pass  # Testing that callback stays put even through another .use()

    assert action_scope.side_effects.buf == b"bar"


@pytest.mark.anyio
async def test_callback_in_callback_error() -> None:
    with pytest.raises(RuntimeError, match="Callback"):
        async with ActionScope.new_scope(TestSideEffects, TestConfig()) as action_scope:
            async with action_scope.use() as interface:

                async def callback(interface: StateInterface[TestSideEffects]) -> None:
                    interface.set_callback(default_async_callback)

                interface.set_callback(callback)


@pytest.mark.anyio
async def test_no_callbacks_if_error() -> None:
    with pytest.raises(Exception, match="This should prevent the callbacks from being called"):
        async with ActionScope.new_scope(TestSideEffects, TestConfig()) as action_scope:
            async with action_scope.use() as interface:

                async def callback(interface: StateInterface[TestSideEffects]) -> None:
                    raise NotImplementedError("Should not get here")  # pragma: no cover

                interface.set_callback(callback)

            async with action_scope.use() as interface:
                raise RuntimeError("This should prevent the callbacks from being called")

    with pytest.raises(Exception, match="This should prevent the callbacks from being called"):
        async with ActionScope.new_scope(TestSideEffects, TestConfig()) as action_scope:
            async with action_scope.use() as interface:

                async def callback2(interface: StateInterface[TestSideEffects]) -> None:
                    raise NotImplementedError("Should not get here")  # pragma: no cover

                interface.set_callback(callback2)

            raise RuntimeError("This should prevent the callbacks from being called")


# TODO: add support, change this test to test it and add a test for nested transactionality
@pytest.mark.anyio
async def test_nested_use_banned(action_scope: ActionScope[TestSideEffects, TestConfig]) -> None:
    async with action_scope.use():
        with pytest.raises(RuntimeError, match="cannot currently support nested transactions"):
            async with action_scope.use():
                pass
