from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
import signal
import sys
from types import FrameType
from typing import AsyncIterator, List, Optional, final

from typing_extensions import Protocol


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
