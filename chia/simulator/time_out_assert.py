from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import pathlib
import sys
import time
from typing import Any, Callable, ClassVar, Dict, Optional, Tuple, final, overload

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.util.misc import caller_file_and_line

log = logging.getLogger(__name__)

system_delays = {
    # based on data from https://github.com/Chia-Network/chia-blockchain/pull/13724
    "github": {
        "darwin": 20,
        "linux": 1,
        "win32": 10,
    },
    # arbitrarily selected
    "local": {
        "darwin": 2,
        "linux": 1,
        "win32": 1,
    },
}


if os.environ.get("GITHUB_ACTIONS") == "true":
    # https://docs.github.com/en/actions/learn-github-actions/environment-variables#default-environment-variables
    _system_delay = system_delays["github"][sys.platform]
else:
    _system_delay = system_delays["local"][sys.platform]


@overload
def adjusted_timeout(timeout: float) -> float:
    ...


@overload
def adjusted_timeout(timeout: None) -> None:
    ...


def adjusted_timeout(timeout: Optional[float]) -> Optional[float]:
    if timeout is None:
        return None

    return timeout + _system_delay


@final
@dataclasses.dataclass(frozen=True)
class TimeOutAssertData:
    # TODO: deal with import directions etc so we can check this
    # if TYPE_CHECKING:
    #     _protocol_check: ClassVar[DataTypeProtocol] = cast("TimeOutAssertData", None)

    tag: ClassVar[str] = "time_out_assert"

    duration: float
    path: pathlib.Path
    line: int
    limit: float
    timed_out: bool

    # TODO: can we make this not required maybe?
    label: str = ""

    __match_args__: ClassVar[Tuple[str, ...]] = ()

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> TimeOutAssertData:
        return cls(
            duration=marshalled["duration"],
            path=pathlib.Path(marshalled["path"]),
            line=int(marshalled["line"]),
            limit=marshalled["limit"],
            timed_out=marshalled["timed_out"],
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "duration": self.duration,
            "path": self.path.as_posix(),
            "line": self.line,
            "limit": self.limit,
            "timed_out": self.timed_out,
        }


async def time_out_assert_custom_interval(timeout: float, interval, function, value=True, *args, **kwargs):
    __tracebackhide__ = True

    # TODO: wrong line when not called directly but instead from the regular time_out_assert?
    entry_file, entry_line = caller_file_and_line()

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
        try:
            # TODO: this import is going the wrong direction
            from tests import ether
        except ImportError:
            pass
        else:
            if ether.record_property is not None:
                data = TimeOutAssertData(
                    duration=duration,
                    path=pathlib.Path(entry_file).relative_to(ether.project_root),
                    line=entry_line,
                    limit=timeout,
                    timed_out=timed_out,
                )

                ether.record_property(
                    # json.dumps(name.marshal(), ensure_ascii=True, sort_keys=True),
                    data.tag,
                    json.dumps(data.marshal(), ensure_ascii=True, sort_keys=True),
                )


async def time_out_assert(timeout: int, function, value=True, *args, **kwargs):
    __tracebackhide__ = True
    await time_out_assert_custom_interval(timeout, 0.05, function, value, *args, **kwargs)


async def time_out_assert_not_none(timeout: float, function, *args, **kwargs):
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


def time_out_messages(incoming_queue: asyncio.Queue, msg_name: str, count: int = 1) -> Callable:
    async def bool_f():
        if incoming_queue.qsize() < count:
            return False
        for _ in range(count):
            response = (await incoming_queue.get()).type
            if ProtocolMessageTypes(response).name != msg_name:
                # log.warning(f"time_out_message: found {response} instead of {msg_name}")
                return False
        return True

    return bool_f
