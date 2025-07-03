from __future__ import annotations

import contextlib
import dataclasses
import functools
import logging
import sys
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, ClassVar, Optional, Self, cast, final

import anyio
import psutil
from typing_extensions import Protocol

from chia.util.task_referencer import manage_referenced_task_cancel_on_exit


class LogCallable(Protocol):
    def __call__(
        self, monitor: ResourceMonitorProtocol, log_level: int, format: str, *args: object, final_report: bool = ...
    ) -> None: ...


class ResourceMonitorProtocol(Protocol):
    label: str

    @classmethod
    @contextlib.contextmanager
    def manage_sync(cls, log: LogCallable) -> Iterator[Self]: ...
    @contextlib.asynccontextmanager
    async def manage_async(self) -> AsyncIterator[None]:
        # yield included to make this a generator as expected by @contextlib.asynccontextmanager
        yield


@dataclasses.dataclass
class MonitorProcessMemory:
    if TYPE_CHECKING:
        _protocol_check: ClassVar[ResourceMonitorProtocol] = cast("MonitorProcessMemory", None)

    log: LogCallable
    period: float = 10.0
    label: str = "process memory usage"
    process: psutil.Process = dataclasses.field(default_factory=psutil.Process)
    log_level: int = logging.DEBUG

    @classmethod
    @contextlib.contextmanager
    def manage_sync(cls, log: LogCallable) -> Iterator[Self]:
        yield cls(log=log)

    @contextlib.asynccontextmanager
    async def manage_async(self) -> AsyncIterator[None]:
        async with manage_referenced_task_cancel_on_exit(self.task()):
            try:
                yield
            finally:
                with anyio.CancelScope(shield=True):
                    self.report(final_report=True)

    async def task(self) -> None:
        while True:
            self.report()
            await anyio.sleep(self.period)

    def report(self, final_report: bool = False) -> None:
        memory_info = self.process.memory_info()
        human_readable = psutil._common.bytes2human(memory_info.rss)
        self.log(self, self.log_level, "%s (%s)", memory_info.rss, human_readable, final_report=final_report)


@final
@dataclasses.dataclass(frozen=True)
class ResourceMonitorConfiguration:
    override_log_level: Optional[int] = None
    process_memory: bool = False

    @classmethod
    def create(cls, service_config: dict[str, object]) -> Self:
        # TODO: support env vars and, as needed, existing configuration entries outside
        #       of the resource monitor configuration
        resource_monitor_config = service_config.get("resource_monitor", {})
        assert isinstance(resource_monitor_config, dict)
        self = cls.unmarshal(resource_monitor_config=resource_monitor_config)
        return self

    @classmethod
    def unmarshal(cls, resource_monitor_config: dict[str, object]) -> Self:
        # TODO: make configuration per monitor possible

        if sys.version_info >= (3, 11):
            log_level_map = logging.getLevelNamesMapping()
        else:
            log_level_map = logging._nameToLevel

        data: dict[str, object] = {}

        sentinel = object()
        override_log_level = resource_monitor_config.get("override_log_level", sentinel)
        if override_log_level is not sentinel:
            if not isinstance(override_log_level, str):
                raise ValueError("override_log_level must be a string")
            if override_log_level is not None:
                override_log_level = log_level_map[override_log_level.upper()]
            data["override_log_level"] = override_log_level

        # pass through / no processing config options
        for name in ["process_memory"]:
            value = resource_monitor_config.get(name, sentinel)
            if value is not sentinel:
                data[name] = value

        # ignoring arg-type due to hacky dynamic handling above
        self = cls(**data)  # type: ignore[arg-type]
        return self

    def enabled_monitor_types(self) -> list[type[ResourceMonitorProtocol]]:
        monitors: list[type[ResourceMonitorProtocol]] = []

        if self.process_memory:
            monitors.append(MonitorProcessMemory)

        return monitors


@final
@dataclasses.dataclass
class ResourceMonitor:
    """Coordinate setup and teardown of resource monitor logging"""

    log: logging.Logger
    config: ResourceMonitorConfiguration
    monitors: list[ResourceMonitorProtocol]

    @classmethod
    @contextlib.contextmanager
    def managed(
        cls,
        log: logging.Logger,
        config: ResourceMonitorConfiguration,
    ) -> Iterator[Self]:
        monitor_types = config.enabled_monitor_types()
        # if len(monitors) != len(set(monitor.label for monitor in monitors)):
        #     raise ValueError("Duplicate monitor labels found")

        try:
            self = cls(
                log=log,
                config=config,
                monitors=[],
            )
            with contextlib.ExitStack() as exit_stack:
                for monitor_type in monitor_types:
                    monitor = exit_stack.enter_context(monitor_type.manage_sync(log=self._create_log_callable()))
                    self.monitors.append(monitor)
            yield self
        finally:
            pass

    @contextlib.asynccontextmanager
    async def manage(self) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as exit_stack:
            try:
                for monitor in self.monitors:
                    await exit_stack.enter_async_context(monitor.manage_async())
                yield
            finally:
                self._write(
                    log_level=logging.INFO,
                    monitor=None,
                    message_format="shutting down resource monitors",
                    final_report=True,
                )

    # @contextlib.asynccontextmanager
    # async def _manage_monitor(self, monitor: ResourceMonitorProtocol) -> AsyncIterator[asyncio.Task[None]]:
    #     log = self._create_log_callable(monitor, final_report=False)
    #
    #     task = create_referenced_task(
    #         monitor.task(log=log),
    #         name=f"resource monitor - {monitor.label}",
    #     )
    #
    #     try:
    #         yield task
    #     finally:
    #         with anyio.CancelScope(shield=True):
    #             task.cancel()
    #             with log_exceptions(
    #                 log=self.log, consume=True, message=f"Error in resource monitor task: {monitor.label}"
    #             ):
    #                 with contextlib.suppress(asyncio.CancelledError):
    #                     await task
    #             await monitor.final_report(log=log)

    def _create_log_callable(self) -> LogCallable:
        # TODO: review the lack of any actual benefit to this layer anymore
        return functools.partial(self._write)

    def _write(
        self,
        log_level: int,
        message_format: str,
        *args: object,
        monitor: Optional[ResourceMonitorProtocol],
        final_report: bool = False,
    ) -> None:
        level = self.config.override_log_level
        if level is None:
            level = log_level

        if not final_report:
            built_message_format = "resource monitors: "
        else:
            built_message_format = "resource monitors - final report: "
        pre_args = []
        if monitor is not None:
            built_message_format += "%s: "
            pre_args.append(monitor.label)

        built_message_format += message_format

        # TODO: maybe use 'sub-loggers' instead of labeling in the message?
        self.log.log(level, built_message_format, *pre_args, *args)
