from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import pathlib
import time
from collections.abc import Awaitable, Iterable
from inspect import getframeinfo, stack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Protocol, TypeVar, cast, final

import chia
import chia._tests
from chia._tests import ether
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message
from chia.util.timing import adjusted_timeout

log = logging.getLogger(__name__)


T = TypeVar("T")


@dataclasses.dataclass(frozen=True)
class DataTypeProtocol(Protocol):
    tag: ClassVar[str]

    line: int
    path: Path
    label: str
    duration: float
    limit: float

    __match_args__: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def unmarshal(cls: type[T], marshalled: dict[str, Any]) -> T: ...

    def marshal(self) -> dict[str, Any]: ...


@final
@dataclasses.dataclass(frozen=True)
class TimeOutAssertData:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[DataTypeProtocol] = cast("TimeOutAssertData", None)

    tag: ClassVar[str] = "time_out_assert"

    duration: float
    path: pathlib.Path
    line: int
    limit: float
    timed_out: bool

    label: str = ""

    __match_args__: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def unmarshal(cls, marshalled: dict[str, Any]) -> TimeOutAssertData:
        return cls(
            duration=marshalled["duration"],
            path=pathlib.Path(marshalled["path"]),
            line=int(marshalled["line"]),
            limit=marshalled["limit"],
            timed_out=marshalled["timed_out"],
        )

    def marshal(self) -> dict[str, Any]:
        return {
            "duration": self.duration,
            "path": self.path.as_posix(),
            "line": self.line,
            "limit": self.limit,
            "timed_out": self.timed_out,
        }


async def time_out_assert_custom_interval(
    timeout: float,
    interval: float,
    function: Callable[..., Any],
    value: object = True,
    *args: object,
    stack_distance: int = 0,
    **kwargs: object,
) -> None:
    __tracebackhide__ = True

    entry_file, entry_line = caller_file_and_line(
        distance=stack_distance + 1,
        relative_to=(
            pathlib.Path(chia.__file__).parent.parent,
            pathlib.Path(chia._tests.__file__).parent.parent,
        ),
    )

    timeout = adjusted_timeout(timeout=timeout)

    start = time.monotonic()
    duration = 0.0
    timed_out = False
    try:
        while True:
            if asyncio.iscoroutinefunction(function):
                f_res = await function(*args, **kwargs)
            else:
                f_res = function(*args, **kwargs)

            if value == f_res:
                return None

            now = time.monotonic()
            duration = now - start

            if duration > timeout:
                timed_out = True
                assert False, f"Timed assertion timed out after {timeout} seconds: expected {value!r}, got {f_res!r}"

            await asyncio.sleep(min(interval, timeout - duration))
    finally:
        if ether.record_property is not None:
            data = TimeOutAssertData(
                duration=duration,
                path=pathlib.Path(entry_file),
                line=entry_line,
                limit=timeout,
                timed_out=timed_out,
            )

            ether.record_property(
                data.tag,
                json.dumps(data.marshal(), ensure_ascii=True, sort_keys=True),
            )


async def time_out_assert(
    timeout: int, function: Callable[..., Any], value: object = True, *args: object, **kwargs: object
) -> None:
    __tracebackhide__ = True
    await time_out_assert_custom_interval(
        timeout,
        0.05,
        function,
        value,
        *args,
        **kwargs,
        stack_distance=1,
    )


async def time_out_assert_not_none(
    timeout: float, function: Callable[..., Any], *args: object, **kwargs: object
) -> None:
    # TODO: rework to leverage time_out_assert_custom_interval() such as by allowing
    #       value to be a callable
    __tracebackhide__ = True

    timeout = adjusted_timeout(timeout=timeout)

    start = time.time()
    while time.time() - start < timeout:
        if asyncio.iscoroutinefunction(function):
            f_res = await function(*args, **kwargs)
        else:
            f_res = function(*args, **kwargs)
        if f_res is not None:
            return None
        await asyncio.sleep(0.05)
    assert False, "Timed assertion timed out"


def time_out_messages(
    incoming_queue: asyncio.Queue[Message], msg_name: str, count: int = 1
) -> Callable[[], Awaitable[bool]]:
    async def bool_f() -> bool:
        if incoming_queue.qsize() < count:
            return False
        for _ in range(count):
            response = (await incoming_queue.get()).type
            if ProtocolMessageTypes(response).name != msg_name:
                # log.warning(f"time_out_message: found {response} instead of {msg_name}")
                return False
        return True

    return bool_f


def caller_file_and_line(distance: int = 1, relative_to: Iterable[Path] = ()) -> tuple[str, int]:
    caller = getframeinfo(stack()[distance + 1][0])

    caller_path = Path(caller.filename)
    options: list[str] = [caller_path.as_posix()]
    for path in relative_to:
        try:
            options.append(caller_path.relative_to(path).as_posix())
        except ValueError:
            pass

    return min(options, key=len), caller.lineno
