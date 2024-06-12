from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
import os
import signal
import sys
from dataclasses import dataclass
from inspect import getframeinfo, stack
from pathlib import Path
from types import FrameType
from typing import (
    AsyncContextManager,
    AsyncIterator,
    ClassVar,
    Collection,
    ContextManager,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    final,
    get_args,
    get_origin,
)

import psutil
from typing_extensions import Protocol

from chia.util.errors import InvalidPathError
from chia.util.ints import uint32, uint64
from chia.util.streamable import Streamable, streamable

T = TypeVar("T")


def get_list_or_len(list_in: Sequence[object], length: bool) -> Union[int, Sequence[object]]:
    return len(list_in) if length else list_in


def validate_directory_writable(path: Path) -> None:
    write_test_path = path / ".write_test"
    try:
        with write_test_path.open("w"):
            pass
        write_test_path.unlink()
    except FileNotFoundError:
        raise InvalidPathError(path, "Directory doesn't exist")
    except OSError:
        raise InvalidPathError(path, "Directory not writable")


if sys.platform == "win32" or sys.platform == "cygwin":
    termination_signals = [signal.SIGBREAK, signal.SIGINT, signal.SIGTERM]
    sendable_termination_signals = [signal.SIGTERM]
else:
    termination_signals = [signal.SIGINT, signal.SIGTERM]
    sendable_termination_signals = termination_signals


@streamable
@dataclasses.dataclass(frozen=True)
class UInt32Range(Streamable):
    start: uint32 = uint32(0)
    stop: uint32 = uint32.MAXIMUM


@streamable
@dataclasses.dataclass(frozen=True)
class UInt64Range(Streamable):
    start: uint64 = uint64(0)
    stop: uint64 = uint64.MAXIMUM


@dataclass(frozen=True)
class Batch(Generic[T]):
    remaining: int
    entries: List[T]


def to_batches(to_split: Collection[T], batch_size: int) -> Iterator[Batch[T]]:
    if batch_size <= 0:
        raise ValueError("to_batches: batch_size must be greater than 0.")
    total_size = len(to_split)
    if total_size == 0:
        return

    if isinstance(to_split, list):
        for batch_start in range(0, total_size, batch_size):
            batch_end = min(batch_start + batch_size, total_size)
            yield Batch(total_size - batch_end, to_split[batch_start:batch_end])
    elif isinstance(to_split, set):
        processed = 0
        entries = []
        for entry in to_split:
            entries.append(entry)
            if len(entries) >= batch_size:
                processed += len(entries)
                yield Batch(total_size - processed, entries)
                entries = []
        if len(entries) > 0:
            processed += len(entries)
            yield Batch(total_size - processed, entries)
    else:
        raise ValueError(f"to_batches: Unsupported type {type(to_split)}")


class Handler(Protocol):
    def __call__(
        self,
        signal_: signal.Signals,
        stack_frame: Optional[FrameType],
        loop: asyncio.AbstractEventLoop,
    ) -> None: ...


class AsyncHandler(Protocol):
    async def __call__(
        self,
        signal_: signal.Signals,
        stack_frame: Optional[FrameType],
        loop: asyncio.AbstractEventLoop,
    ) -> None: ...


@final
@dataclasses.dataclass
class SignalHandlers:
    tasks: List[asyncio.Task[None]] = dataclasses.field(default_factory=list)

    @classmethod
    @contextlib.asynccontextmanager
    async def manage(cls) -> AsyncIterator[SignalHandlers]:
        self = cls()
        try:
            yield self
        finally:
            # TODO: log errors?
            # TODO: return to previous signal handlers?
            await asyncio.gather(*self.tasks)

    def remove_done_handlers(self) -> None:
        self.tasks = [task for task in self.tasks if not task.done()]

    def loop_safe_sync_signal_handler_for_async(
        self,
        signal_: signal.Signals,
        stack_frame: Optional[FrameType],
        loop: asyncio.AbstractEventLoop,
        handler: AsyncHandler,
    ) -> None:
        self.remove_done_handlers()

        task = asyncio.create_task(
            handler(signal_=signal_, stack_frame=stack_frame, loop=loop),
        )
        self.tasks.append(task)

    def threadsafe_sync_signal_handler_for_async(
        self,
        signal_: signal.Signals,
        stack_frame: Optional[FrameType],
        loop: asyncio.AbstractEventLoop,
        handler: AsyncHandler,
    ) -> None:
        loop.call_soon_threadsafe(
            functools.partial(
                self.loop_safe_sync_signal_handler_for_async,
                signal_=signal_,
                stack_frame=stack_frame,
                loop=loop,
                handler=handler,
            ),
        )

    def setup_sync_signal_handler(self, handler: Handler) -> None:
        loop = asyncio.get_event_loop()

        if sys.platform == "win32" or sys.platform == "cygwin":

            def ensure_signal_object_not_int(
                signal_: int,
                stack_frame: Optional[FrameType],
                *,
                handler: Handler = handler,
                loop: asyncio.AbstractEventLoop = loop,
            ) -> None:
                signal_ = signal.Signals(signal_)
                handler(signal_=signal_, stack_frame=stack_frame, loop=loop)

            for signal_ in [signal.SIGBREAK, signal.SIGINT, signal.SIGTERM]:
                signal.signal(signal_, ensure_signal_object_not_int)
        else:
            for signal_ in [signal.SIGINT, signal.SIGTERM]:
                loop.add_signal_handler(
                    signal_,
                    functools.partial(handler, signal_=signal_, stack_frame=None, loop=loop),
                )

    def setup_async_signal_handler(self, handler: AsyncHandler) -> None:
        # https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.add_signal_handler
        # > a callback registered with this function is allowed to interact with the event
        # > loop
        #
        # This is a bit vague so let's just use a thread safe call for Windows
        # compatibility.

        self.setup_sync_signal_handler(
            handler=functools.partial(self.threadsafe_sync_signal_handler_for_async, handler=handler)
        )


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
