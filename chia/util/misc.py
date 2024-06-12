from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import os
import sys
from dataclasses import dataclass
from inspect import getframeinfo, stack
from pathlib import Path
from typing import (
    AsyncContextManager,
    AsyncIterator,
    ClassVar,
    ContextManager,
    Generic,
    Iterable,
    Iterator,
    List,
    Tuple,
    Type,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

import psutil

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


class ValuedEventSentinel:
    pass


@dataclasses.dataclass
class ValuedEvent(Generic[T]):
    _value_sentinel: ClassVar[ValuedEventSentinel] = ValuedEventSentinel()

    _event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    _value: Union[ValuedEventSentinel, T] = _value_sentinel

    def set(self, value: T) -> None:
        if not isinstance(self._value, ValuedEventSentinel):
            raise Exception("Value already set")
        self._value = value
        self._event.set()

    async def wait(self) -> T:
        await self._event.wait()
        if isinstance(self._value, ValuedEventSentinel):
            raise Exception("Value not set despite event being set")
        return self._value


def available_logical_cores() -> int:
    if sys.platform == "darwin":
        count = os.cpu_count()
        assert count is not None
        return count

    cores = len(psutil.Process().cpu_affinity())

    if sys.platform == "win32":
        cores = min(61, cores)  # https://github.com/python/cpython/issues/89240

    return cores


def caller_file_and_line(distance: int = 1, relative_to: Iterable[Path] = ()) -> Tuple[str, int]:
    caller = getframeinfo(stack()[distance + 1][0])

    caller_path = Path(caller.filename)
    options: List[str] = [caller_path.as_posix()]
    for path in relative_to:
        try:
            options.append(caller_path.relative_to(path).as_posix())
        except ValueError:
            pass

    return min(options, key=len), caller.lineno


def satisfies_hint(obj: T, type_hint: Type[T]) -> bool:
    """
    Check if an object satisfies a type hint.
    This is a simplified version of `isinstance` that also handles generic types.
    """
    # Start from the initial type hint
    object_hint_pairs = [(obj, type_hint)]
    while len(object_hint_pairs) > 0:
        obj, type_hint = object_hint_pairs.pop()
        origin = get_origin(type_hint)
        args = get_args(type_hint)
        if origin:
            # Handle generic types
            if not isinstance(obj, origin):
                return False
            if len(args) > 0:
                # Tuple[T, ...] gets handled just like List[T]
                if origin is list or (origin is tuple and args[-1] is Ellipsis):
                    object_hint_pairs.extend((item, args[0]) for item in obj)
                elif origin is tuple:
                    object_hint_pairs.extend((item, arg) for item, arg in zip(obj, args))
                elif origin is dict:
                    object_hint_pairs.extend((k, args[0]) for k in obj.keys())
                    object_hint_pairs.extend((v, args[1]) for v in obj.values())
                else:
                    raise NotImplementedError(f"Type {origin} is not yet supported")
        else:
            # Handle concrete types
            if type(obj) is not type_hint:
                return False
    return True
