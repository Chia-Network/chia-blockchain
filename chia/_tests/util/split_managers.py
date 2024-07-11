from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import AsyncContextManager, AsyncIterator, ContextManager, Generic, Iterator, List, TypeVar

T = TypeVar("T")


@dataclass
class SplitManager(Generic[T]):
    # NOTE: only for transitional testing use, please avoid usage
    manager: ContextManager[object]
    object: T
    _entered: bool = False
    _exited: bool = False

    def enter(self) -> None:
        messages: List[str] = []
        if self._entered:
            messages.append("already entered")
        if self._exited:
            messages.append("already exited")
        if len(messages) > 0:
            raise Exception(", ".join(messages))

        self._entered = True
        self.manager.__enter__()

    def exit(self, if_needed: bool = False) -> None:
        if if_needed and (not self._entered or self._exited):
            return

        messages: List[str] = []
        if not self._entered:
            messages.append("not yet entered")
        if self._exited:
            messages.append("already exited")
        if len(messages) > 0:
            raise Exception(", ".join(messages))

        self._exited = True
        self.manager.__exit__(None, None, None)


@dataclass
class SplitAsyncManager(Generic[T]):
    # NOTE: only for transitional testing use, please avoid usage
    manager: AsyncContextManager[object]
    object: T
    _entered: bool = False
    _exited: bool = False

    async def enter(self) -> None:
        messages: List[str] = []
        if self._entered:
            messages.append("already entered")
        if self._exited:
            messages.append("already exited")
        if len(messages) > 0:
            raise Exception(", ".join(messages))

        self._entered = True
        await self.manager.__aenter__()

    async def exit(self, if_needed: bool = False) -> None:
        if if_needed and (not self._entered or self._exited):
            return

        messages: List[str] = []
        if not self._entered:
            messages.append("not yet entered")
        if self._exited:
            messages.append("already exited")
        if len(messages) > 0:
            raise Exception(", ".join(messages))

        self._exited = True
        await self.manager.__aexit__(None, None, None)


@contextlib.contextmanager
def split_manager(manager: ContextManager[object], object: T) -> Iterator[SplitManager[T]]:
    # NOTE: only for transitional testing use, please avoid usage
    split = SplitManager(manager=manager, object=object)
    try:
        yield split
    finally:
        split.exit(if_needed=True)


@contextlib.asynccontextmanager
async def split_async_manager(manager: AsyncContextManager[object], object: T) -> AsyncIterator[SplitAsyncManager[T]]:
    # NOTE: only for transitional testing use, please avoid usage
    split = SplitAsyncManager(manager=manager, object=object)
    try:
        yield split
    finally:
        await split.exit(if_needed=True)
