from __future__ import annotations

import contextlib
import dataclasses
import enum
import functools
import gc
import json
import logging
import os
import pathlib
import ssl
import subprocess
import sys
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import Enum
from inspect import getframeinfo, stack
from pathlib import Path
from statistics import mean
from textwrap import dedent
from time import thread_time
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Collection,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Protocol,
    TextIO,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    final,
)

import aiohttp
import pytest

# TODO: update after resolution in https://github.com/pytest-dev/pytest/issues/7469
from _pytest.nodes import Node
from aiohttp import web
from chia_rs import Coin

import chia
import chia._tests
from chia._tests import ether
from chia._tests.core.data_layer.util import ChiaRoot
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.full_node.full_node import FullNode
from chia.full_node.mempool import Mempool
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.full_block import FullBlock
from chia.types.peer_info import PeerInfo
from chia.util.batches import to_batches
from chia.util.hash import std_hash
from chia.util.ints import uint16, uint32, uint64
from chia.util.network import WebServer
from chia.wallet.util.compute_hints import HintedCoin
from chia.wallet.wallet_node import WalletNode


class GcMode(enum.Enum):
    nothing = enum.auto
    precollect = enum.auto
    disable = enum.auto
    enable = enum.auto


@contextlib.contextmanager
def manage_gc(mode: GcMode) -> Iterator[None]:
    if mode == GcMode.nothing:
        yield
    elif mode == GcMode.precollect:
        gc.collect()
        yield
    elif mode == GcMode.disable:
        was_enabled = gc.isenabled()
        gc.disable()
        try:
            yield
        finally:
            if was_enabled:
                gc.enable()
    elif mode == GcMode.enable:
        was_enabled = gc.isenabled()
        gc.enable()
        try:
            yield
        finally:
            if not was_enabled:
                gc.disable()


@dataclasses.dataclass(frozen=True)
class RuntimeResults:
    start: float
    end: float
    duration: float
    entry_file: str
    entry_line: int
    overhead: Optional[float]

    def block(self, label: str = "") -> str:
        # The entry line is reported starting at the beginning of the line to trigger
        # PyCharm to highlight as a link to the source.

        return dedent(
            f"""\
            Measuring runtime: {label}
            {self.entry_line}
                run time: {self.duration}
                overhead: {self.overhead if self.overhead is not None else "not measured"}
            """
        )


@final
@dataclasses.dataclass(frozen=True)
class AssertRuntimeResults:
    start: float
    end: float
    duration: float
    entry_file: str
    entry_line: int
    overhead: Optional[float]
    limit: float
    ratio: float

    @classmethod
    def from_runtime_results(
        cls, results: RuntimeResults, limit: float, entry_file: str, entry_line: int, overhead: Optional[float]
    ) -> AssertRuntimeResults:
        return cls(
            start=results.start,
            end=results.end,
            duration=results.duration,
            limit=limit,
            ratio=results.duration / limit,
            entry_file=entry_file,
            entry_line=entry_line,
            overhead=overhead,
        )

    def block(self, label: str = "") -> str:
        # The entry line is reported starting at the beginning of the line to trigger
        # PyCharm to highlight as a link to the source.

        return dedent(
            f"""\
            Asserting maximum duration: {label}
            {self.entry_file}:{self.entry_line}
                run time: {self.duration}
                overhead: {self.overhead if self.overhead is not None else "not measured"}
                 allowed: {self.limit}
                 percent: {self.percent_str()}
            """
        )

    def message(self) -> str:
        return f"{self.duration} seconds not less than {self.limit} seconds ( {self.percent_str()} )"

    def passed(self) -> bool:
        return self.duration < self.limit

    def percent(self) -> float:
        return self.ratio * 100

    def percent_str(self) -> str:
        return f"{self.percent():.0f} %"


def measure_overhead(
    manager_maker: Callable[
        [], contextlib.AbstractContextManager[Union[Future[RuntimeResults], Future[AssertRuntimeResults]]]
    ],
    cycles: int = 10,
) -> float:
    times: List[float] = []

    for _ in range(cycles):
        with manager_maker() as results:
            pass

        times.append(results.result(timeout=0).duration)

    overhead = mean(times)

    return overhead


@contextlib.contextmanager
def measure_runtime(
    label: str = "",
    clock: Callable[[], float] = thread_time,
    gc_mode: GcMode = GcMode.disable,
    overhead: Optional[float] = None,
    print_results: bool = True,
) -> Iterator[Future[RuntimeResults]]:
    entry_file, entry_line = caller_file_and_line(
        relative_to=(
            pathlib.Path(chia.__file__).parent.parent,
            pathlib.Path(chia._tests.__file__).parent.parent,
        )
    )

    results_future: Future[RuntimeResults] = Future()

    with manage_gc(mode=gc_mode):
        start = clock()

        try:
            yield results_future
        finally:
            end = clock()

            duration = end - start
            if overhead is not None:
                duration -= overhead

            results = RuntimeResults(
                start=start,
                end=end,
                duration=duration,
                entry_file=entry_file,
                entry_line=entry_line,
                overhead=overhead,
            )
            results_future.set_result(results)

            if print_results:
                print(results.block(label=label))


@final
@dataclasses.dataclass(frozen=True)
class BenchmarkData:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[DataTypeProtocol] = cast("BenchmarkData", None)

    tag: ClassVar[str] = "benchmark"

    duration: float
    path: pathlib.Path
    line: int
    limit: float

    label: str

    __match_args__: ClassVar[Tuple[str, ...]] = ()

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> BenchmarkData:
        return cls(
            duration=marshalled["duration"],
            path=pathlib.Path(marshalled["path"]),
            line=int(marshalled["line"]),
            limit=marshalled["limit"],
            label=marshalled["label"],
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "duration": self.duration,
            "path": self.path.as_posix(),
            "line": self.line,
            "limit": self.limit,
            "label": self.label,
        }


@final
@dataclasses.dataclass
class _AssertRuntime:
    """Prepare for, measure, and assert about the time taken by code in the context.

    Defaults are set for single-threaded CPU usage timing without garbage collection.

    In general, there is no generally correct setup for benchmarking.  Only measuring
    a single thread's time using the CPU is not very useful for multithreaded or
    multiprocessed code.  Disabling garbage collection, or forcing it ahead of time,
    makes the benchmark not identify any issues the code may introduce in terms of
    actually causing relevant gc slowdowns.  And so on...

    Produces output of the following form.

        Asserting maximum duration: full block
        /home/altendky/repos/chia-blockchain/tests/core/full_node/test_performance.py:187
            run time: 0.027789528900002837
            allowed: 0.1
            percent: 28 %
    """

    # A class is only being used here, to make __tracebackhide__ work.
    # https://github.com/pytest-dev/pytest/issues/2057

    seconds: float
    # TODO: Optional?
    label: str = ""
    clock: Callable[[], float] = thread_time
    gc_mode: GcMode = GcMode.disable
    print: bool = True
    overhead: Optional[float] = None
    entry_file: Optional[str] = None
    entry_line: Optional[int] = None
    _results: Optional[AssertRuntimeResults] = None
    runtime_manager: Optional[contextlib.AbstractContextManager[Future[RuntimeResults]]] = None
    runtime_results_callable: Optional[Future[RuntimeResults]] = None
    enable_assertion: bool = True

    def __enter__(self) -> Future[AssertRuntimeResults]:
        self.entry_file, self.entry_line = caller_file_and_line(
            relative_to=(
                pathlib.Path(chia.__file__).parent.parent,
                pathlib.Path(chia._tests.__file__).parent.parent,
            )
        )

        self.runtime_manager = measure_runtime(
            clock=self.clock, gc_mode=self.gc_mode, overhead=self.overhead, print_results=False
        )
        self.runtime_results_callable = self.runtime_manager.__enter__()
        self.results_callable: Future[AssertRuntimeResults] = Future()

        return self.results_callable

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if (
            self.entry_file is None
            or self.entry_line is None
            or self.runtime_manager is None
            or self.runtime_results_callable is None
        ):
            raise Exception("Context manager must be entered before exiting")

        self.runtime_manager.__exit__(exc_type, exc, traceback)

        runtime = self.runtime_results_callable.result(timeout=0)
        results = AssertRuntimeResults.from_runtime_results(
            results=runtime,
            limit=self.seconds,
            entry_file=self.entry_file,
            entry_line=self.entry_line,
            overhead=self.overhead,
        )

        self.results_callable.set_result(results)

        if self.print:
            print(results.block(label=self.label))

        if ether.record_property is not None:
            data = BenchmarkData(
                duration=results.duration,
                path=pathlib.Path(self.entry_file),
                line=self.entry_line,
                limit=self.seconds,
                label=self.label,
            )

            ether.record_property(  # pylint: disable=E1102
                data.tag,
                json.dumps(data.marshal(), ensure_ascii=True, sort_keys=True),
            )

        if exc_type is None and self.enable_assertion:
            __tracebackhide__ = True
            assert runtime.duration < self.seconds, results.message()


@final
@dataclasses.dataclass
class BenchmarkRunner:
    enable_assertion: bool = True
    test_id: Optional[TestId] = None
    overhead: Optional[float] = None

    def assert_runtime(self, *args: Any, **kwargs: Any) -> _AssertRuntime:
        kwargs.setdefault("enable_assertion", self.enable_assertion)
        kwargs.setdefault("overhead", self.overhead)
        return _AssertRuntime(*args, **kwargs)


@contextlib.contextmanager
def assert_rpc_error(error: str) -> Iterator[None]:
    with pytest.raises(ValueError) as exception_info:
        yield
    assert error in exception_info.value.args[0]["error"]


@contextlib.contextmanager
def closing_chia_root_popen(chia_root: ChiaRoot, args: List[str]) -> Iterator[subprocess.Popen[Any]]:
    environment = {**os.environ, "CHIA_ROOT": os.fspath(chia_root.path)}

    with subprocess.Popen(args=args, env=environment) as process:
        try:
            yield process
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


# https://github.com/pytest-dev/pytest/blob/7.3.1/src/_pytest/mark/__init__.py#L45
Marks = Union[pytest.MarkDecorator, Collection[Union[pytest.MarkDecorator, pytest.Mark]]]


class DataCase(Protocol):
    marks: Marks

    @property
    def id(self) -> str: ...


def datacases(*cases: DataCase, _name: str = "case") -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        argnames=_name,
        argvalues=[pytest.param(case, id=case.id, marks=case.marks) for case in cases],
    )


class DataCasesDecorator(Protocol):
    def __call__(self, *cases: DataCase, _name: str = "case") -> pytest.MarkDecorator: ...


def named_datacases(name: str) -> DataCasesDecorator:
    return functools.partial(datacases, _name=name)


def boolean_datacases(name: str, false: str, true: str) -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        argnames=name,
        argvalues=[
            pytest.param(False, id=false),
            pytest.param(True, id=true),
        ],
    )


@dataclasses.dataclass
class CoinGenerator:
    _seed: int = -1

    def _get_hash(self) -> bytes32:
        self._seed += 1
        return std_hash(self._seed.to_bytes(length=32, byteorder="big"))

    def _get_amount(self) -> uint64:
        self._seed += 1
        return uint64(self._seed)

    def get(self, parent_coin_id: Optional[bytes32] = None, include_hint: bool = True) -> HintedCoin:
        if parent_coin_id is None:
            parent_coin_id = self._get_hash()
        hint = None
        if include_hint:
            hint = self._get_hash()
        return HintedCoin(Coin(parent_coin_id, self._get_hash(), self._get_amount()), hint)


def coin_creation_args(hinted_coin: HintedCoin) -> List[Any]:
    if hinted_coin.hint is not None:
        memos = [hinted_coin.hint]
    else:
        memos = []
    return [ConditionOpcode.CREATE_COIN, hinted_coin.coin.puzzle_hash, hinted_coin.coin.amount, memos]


def create_logger(file: TextIO = sys.stdout) -> logging.Logger:
    logger = logging.getLogger()
    logger.setLevel(level=logging.DEBUG)
    stream_handler = logging.StreamHandler(stream=file)
    log_date_format = "%Y-%m-%dT%H:%M:%S"
    file_log_formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s",
        datefmt=log_date_format,
    )
    stream_handler.setFormatter(file_log_formatter)
    logger.addHandler(hdlr=stream_handler)

    return logger


def invariant_check_mempool(mempool: Mempool) -> None:
    with mempool._db_conn as conn:
        cursor = conn.execute("SELECT COALESCE(SUM(cost), 0), COALESCE(SUM(fee), 0) FROM tx")
        val = cursor.fetchone()
        assert (mempool._total_cost, mempool._total_fee) == val


async def wallet_height_at_least(wallet_node: WalletNode, h: uint32) -> bool:
    height = await wallet_node.wallet_state_manager.blockchain.get_finished_sync_up_to()
    return height == h


@final
@dataclass
class RecordingWebServer:
    web_server: WebServer
    requests: List[web.Request] = field(default_factory=list)

    @classmethod
    async def create(
        cls,
        hostname: str,
        port: uint16,
        max_request_body_size: int = 1024**2,  # Default `client_max_size` from web.Application
        ssl_context: Optional[ssl.SSLContext] = None,
        prefer_ipv6: bool = False,
    ) -> RecordingWebServer:
        web_server = await WebServer.create(
            hostname=hostname,
            port=port,
            max_request_body_size=max_request_body_size,
            ssl_context=ssl_context,
            prefer_ipv6=prefer_ipv6,
            start=False,
        )

        self = cls(web_server=web_server)
        routes = [web.route(method="*", path=route, handler=func) for (route, func) in self.get_routes().items()]
        web_server.add_routes(routes=routes)
        await web_server.start()
        return self

    def get_routes(self) -> Dict[str, Callable[[web.Request], Awaitable[web.Response]]]:
        return {"/{path:.*}": self.handler}

    async def handler(self, request: web.Request) -> web.Response:
        self.requests.append(request)

        request_json = await request.json()
        if isinstance(request_json, dict) and "response" in request_json:
            response = request_json["response"]
        else:
            response = {"success": True}

        return aiohttp.web.json_response(data=response)

    async def await_closed(self) -> None:
        self.web_server.close()
        await self.web_server.await_closed()


@final
@dataclasses.dataclass(frozen=True)
class TestId:
    platform: str
    test_path: Tuple[str, ...]
    ids: Tuple[str, ...]

    @classmethod
    def create(cls, node: Node, platform: str = sys.platform) -> TestId:
        test_path: List[str] = []
        temp_node = node
        while True:
            name: str
            if isinstance(temp_node, pytest.Function):
                name = temp_node.originalname
            elif isinstance(temp_node, pytest.Package):
                # must check before pytest.Module since Package is a subclass
                name = temp_node.name
            elif isinstance(temp_node, pytest.Module):
                name = temp_node.name[:-3]
            else:
                name = temp_node.name
            test_path.insert(0, name)
            if isinstance(temp_node.parent, pytest.Session) or temp_node.parent is None:
                break
            temp_node = temp_node.parent

        # TODO: can we avoid parsing the id's etc from the node name?
        test_name, delimiter, rest = node.name.partition("[")
        ids: Tuple[str, ...]
        if delimiter == "":
            ids = ()
        else:
            ids = tuple(rest.rstrip("]").split("-"))

        return cls(
            platform=platform,
            test_path=tuple(test_path),
            ids=ids,
        )

    @classmethod
    def unmarshal(cls, marshalled: Dict[str, Any]) -> TestId:
        return cls(
            platform=marshalled["platform"],
            test_path=tuple(marshalled["test_path"]),
            ids=tuple(marshalled["ids"]),
        )

    def marshal(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "test_path": self.test_path,
            "ids": self.ids,
        }


T = TypeVar("T")


@dataclasses.dataclass(frozen=True)
class DataTypeProtocol(Protocol):
    tag: ClassVar[str]

    line: int
    path: Path
    label: str
    duration: float
    limit: float

    __match_args__: ClassVar[Tuple[str, ...]] = ()

    @classmethod
    def unmarshal(cls: Type[T], marshalled: Dict[str, Any]) -> T: ...

    def marshal(self) -> Dict[str, Any]: ...


T_ComparableEnum = TypeVar("T_ComparableEnum", bound="ComparableEnum")


class ComparableEnum(Enum):
    def __lt__(self: T_ComparableEnum, other: T_ComparableEnum) -> object:
        if self.__class__ is not other.__class__:
            return NotImplemented

        return self.value.__lt__(other.value)

    def __le__(self: T_ComparableEnum, other: T_ComparableEnum) -> object:
        if self.__class__ is not other.__class__:
            return NotImplemented

        return self.value.__le__(other.value)

    def __eq__(self: T_ComparableEnum, other: object) -> bool:
        if self.__class__ is not other.__class__:
            return False

        return cast(bool, self.value.__eq__(cast(T_ComparableEnum, other).value))

    def __ne__(self: T_ComparableEnum, other: object) -> bool:
        if self.__class__ is not other.__class__:
            return True

        return cast(bool, self.value.__ne__(cast(T_ComparableEnum, other).value))

    def __gt__(self: T_ComparableEnum, other: T_ComparableEnum) -> object:
        if self.__class__ is not other.__class__:
            return NotImplemented

        return self.value.__gt__(other.value)

    def __ge__(self: T_ComparableEnum, other: T_ComparableEnum) -> object:
        if self.__class__ is not other.__class__:
            return NotImplemented

        return self.value.__ge__(other.value)


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


async def add_blocks_in_batches(
    blocks: List[FullBlock],
    full_node: FullNode,
    header_hash: Optional[bytes32] = None,
) -> None:
    if header_hash is None:
        diff = full_node.constants.DIFFICULTY_STARTING
        ssi = full_node.constants.SUB_SLOT_ITERS_STARTING
    else:
        block_record = await full_node.blockchain.get_block_record_from_db(header_hash)
        ssi, diff = get_next_sub_slot_iters_and_difficulty(
            full_node.constants, True, block_record, full_node.blockchain
        )
    prev_ses_block = None
    for block_batch in to_batches(blocks, 64):
        b = block_batch.entries[0]
        if (b.height % 128) == 0:
            print(f"main chain: {b.height:4} weight: {b.weight}")
        success, _, ssi, diff, prev_ses_block, err = await full_node.add_block_batch(
            block_batch.entries,
            PeerInfo("0.0.0.0", 0),
            None,
            current_ssi=ssi,
            current_difficulty=diff,
            prev_ses_block=prev_ses_block,
        )
        assert err is None
        assert success is True
