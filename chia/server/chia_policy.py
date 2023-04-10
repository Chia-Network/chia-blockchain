from __future__ import annotations

import asyncio
import logging
import socket
import ssl
import struct
import sys

if sys.platform == "win32":
    import _overlapped
    import _winapi

from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional, Tuple, Union

from typing_extensions import Protocol, TypeAlias

# https://github.com/python/asyncio/pull/448
global_max_concurrent_connections: int = 250


if TYPE_CHECKING:
    # typeshed, for mypy, doesn't include the private attributes.  Documenting them
    # here so the actual inheriting code can be left tidy.

    # https://github.com/python/typeshed/blob/d084079fc3d89a7b51b89095ad67762944e0ace3/stdlib/asyncio/base_events.pyi#L22-L25
    # _ProtocolFactory: TypeAlias = Callable[[], asyncio.protocols.BaseProtocol]
    class _ProtocolFactory(Protocol):
        # https://github.com/python/mypy/issues/6910#issuecomment-1081107831
        # https://github.com/python/typeshed/pull/5718/files
        def __call__(self) -> asyncio.protocols.BaseProtocol:
            ...

    _SSLContext: TypeAlias = Union[bool, None, ssl.SSLContext]

    # https://github.com/python/cpython/blob/v3.10.8/Lib/asyncio/base_events.py#L389
    # https://github.com/python/typeshed/blob/d084079fc3d89a7b51b89095ad67762944e0ace3/stdlib/asyncio/base_events.pyi#L64
    class EventsAbstractEventLoop(asyncio.events.AbstractEventLoop):
        # https://github.com/python/cpython/blob/v3.10.8/Lib/asyncio/selector_events.py#L142
        # https://github.com/python/cpython/blob/v3.10.8/Lib/asyncio/proactor_events.py#L814
        def _start_serving(
            self,
            protocol_factory: _ProtocolFactory,
            sock: socket.socket,
            sslcontext: Optional[_SSLContext] = ...,
            server: Optional[asyncio.base_events.Server] = ...,
            backlog: int = ...,
            # https://github.com/python/cpython/blob/v3.10.8/Lib/asyncio/constants.py#L16
            ssl_handshake_timeout: Optional[float] = ...,
        ) -> None:
            ...

    # https://github.com/python/cpython/blob/v3.10.8/Lib/asyncio/base_events.py#L278
    # https://github.com/python/typeshed/blob/d084079fc3d89a7b51b89095ad67762944e0ace3/stdlib/asyncio/base_events.pyi#L27
    class BaseEventsServer(asyncio.base_events.Server):
        if sys.platform == "win32" and sys.version_info >= (3, 8):
            _loop: ChiaProactorEventLoop
        else:
            _loop: EventsAbstractEventLoop
        _sockets: Iterable[socket.socket]
        _active_count: int
        _protocol_factory: _ProtocolFactory
        _backlog: int
        _ssl_context: _SSLContext
        _ssl_handshake_timeout: Optional[float]

        def _attach(self) -> None:
            ...

        def _detach(self) -> None:
            ...

        def _start_serving(self) -> None:
            ...

    if sys.platform == "win32":
        # https://github.com/python/cpython/blob/v3.10.8/Lib/asyncio/windows_events.py#L48
        class _OverlappedFuture(asyncio.Future[Any]):
            ...

        # https://github.com/python/cpython/blob/v3.10.8/Lib/asyncio/windows_events.py#L410
        # https://github.com/python/typeshed/blob/d084079fc3d89a7b51b89095ad67762944e0ace3/stdlib/asyncio/windows_events.pyi#L44
        class IocpProactor(asyncio.windows_events.IocpProactor):
            _loop: Optional[asyncio.events.AbstractEventLoop]

            def _register_with_iocp(self, obj: object) -> None:
                ...

            def _register(
                self,
                ov: _overlapped.Overlapped,
                obj: socket.socket,
                callback: Callable[[object, socket.socket, _overlapped.Overlapped], Tuple[socket.socket, object]],
            ) -> _OverlappedFuture:
                ...

            def _get_accept_socket(self, family: socket.AddressFamily) -> socket.socket:
                ...

        # https://github.com/python/cpython/blob/v3.10.8/Lib/asyncio/windows_events.py#L309
        # https://github.com/python/typeshed/blob/d084079fc3d89a7b51b89095ad67762944e0ace3/stdlib/asyncio/windows_events.pyi#L35
        class ProactorEventLoop(asyncio.windows_events.ProactorEventLoop):
            # Actually provided on BaseProactorEventLoop
            # https://github.com/python/cpython/blob/v3.10.8/Lib/asyncio/proactor_events.py#L627
            # https://github.com/python/typeshed/blob/d084079fc3d89a7b51b89095ad67762944e0ace3/stdlib/asyncio/proactor_events.pyi#L75
            _proactor: Any

else:
    BaseEventsServer = asyncio.base_events.Server
    if sys.platform == "win32":
        IocpProactor = asyncio.windows_events.IocpProactor
        ProactorEventLoop = asyncio.windows_events.ProactorEventLoop


class PausableServer(BaseEventsServer):
    _paused: bool
    max_concurrent_connections: int

    # https://github.com/python/typeshed/blob/d084079fc3d89a7b51b89095ad67762944e0ace3/stdlib/asyncio/base_events.pyi#L40-L48
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        sockets: Iterable[socket.socket],
        protocol_factory: _ProtocolFactory,
        ssl_context: _SSLContext,
        backlog: int,
        ssl_handshake_timeout: Optional[float],
        max_concurrent_connections: Optional[int] = None,
    ) -> None:
        super().__init__(
            loop=loop,
            sockets=sockets,
            protocol_factory=protocol_factory,
            ssl_context=ssl_context,
            backlog=backlog,
            ssl_handshake_timeout=ssl_handshake_timeout,
        )
        self._paused = False
        self.max_concurrent_connections = (
            max_concurrent_connections if max_concurrent_connections is not None else global_max_concurrent_connections
        )

    def _attach(self) -> None:
        super()._attach()
        logging.getLogger(__name__).debug(f"New connection. Total connections: {self._active_count}")
        if not self._paused and self._active_count >= self.max_concurrent_connections:
            self._chia_pause()

    def _detach(self) -> None:
        super()._detach()
        logging.getLogger(__name__).debug(f"Connection lost. Total connections: {self._active_count}")
        if (
            self._active_count > 0
            and self._sockets is not None
            and self._paused
            and self._active_count < self.max_concurrent_connections
        ):
            self._chia_resume()

    def _chia_pause(self) -> None:
        """Pause future calls to accept()."""
        self._paused = True
        if sys.platform == "win32" and sys.version_info >= (3, 8):
            # proactor
            self._loop.disable_connections()
        else:
            # selector
            for sock in self._sockets:
                self._loop.remove_reader(sock.fileno())
        logging.getLogger(__name__).debug("Maximum number of connections reached, paused accepting connections.")

    def _chia_resume(self) -> None:
        """Resume use of accept() on listening socket(s)."""
        self._paused = False
        if sys.platform == "win32" and sys.version_info >= (3, 8):
            # proactor
            self._loop.enable_connections()
        else:
            # selector
            for sock in self._sockets:
                self._loop._start_serving(
                    self._protocol_factory,
                    sock,
                    self._ssl_context,
                    self,
                    self._backlog,
                    self._ssl_handshake_timeout,
                )
        logging.getLogger(__name__).debug("Resumed accepting connections.")


async def _chia_create_server(
    cls: Any,
    protocol_factory: _ProtocolFactory,
    host: Any,
    port: Any,
    *,
    family: socket.AddressFamily = socket.AF_UNSPEC,
    flags: socket.AddressInfo = socket.AI_PASSIVE,
    sock: Any = None,
    backlog: int = 100,
    ssl: _SSLContext = None,
    reuse_address: Optional[bool] = None,
    reuse_port: Optional[bool] = None,
    ssl_handshake_timeout: Optional[float] = 30,
    start_serving: bool = True,
) -> PausableServer:
    server: BaseEventsServer = await cls.create_server(
        protocol_factory=protocol_factory,
        host=host,
        port=port,
        family=family,
        flags=flags,
        sock=sock,
        backlog=backlog,
        ssl=ssl,
        reuse_address=reuse_address,
        reuse_port=reuse_port,
        # TODO: tweaked
        ssl_handshake_timeout=ssl_handshake_timeout if ssl is not None else None,
        start_serving=False,
    )
    pausable_server = PausableServer(
        loop=server._loop,
        sockets=server._sockets,
        protocol_factory=server._protocol_factory,
        ssl_context=server._ssl_context,
        backlog=server._backlog,
        ssl_handshake_timeout=server._ssl_handshake_timeout,
    )
    if start_serving:
        pausable_server._start_serving()
        # Skip one loop iteration so that all 'loop.add_reader'
        # go through.
        await asyncio.sleep(0)

    return pausable_server


class ChiaSelectorEventLoop(asyncio.SelectorEventLoop):
    # Ignoring lack of typing since we are passing through and also never call this
    # ourselves. There may be a good solution if needed in the future.  We should
    # generally get a warning about calling an untyped function in case we do.
    async def create_server(self, *args, **kwargs) -> PausableServer:  # type: ignore[no-untyped-def]
        return await _chia_create_server(super(), *args, **kwargs)


if sys.platform == "win32":

    class ChiaProactor(IocpProactor):
        allow_connections: bool

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.allow_connections = True

        def enable_connections(self) -> None:
            self.allow_connections = True

        def disable_connections(self) -> None:
            self.allow_connections = False

        async def _chia_accept_loop(self, listener: socket.socket) -> Tuple[socket.socket, Tuple[object, ...]]:
            while True:
                # TODO: switch to Event code.
                while not self.allow_connections:
                    await asyncio.sleep(0.01)

                try:
                    return await self._chia_accept(listener)
                except WindowsError as exc:  # pylint: disable=E0602
                    if exc.winerror not in (_winapi.ERROR_NETNAME_DELETED, _winapi.ERROR_OPERATION_ABORTED):
                        raise

        def _chia_accept(self, listener: socket.socket) -> asyncio.Future[Tuple[socket.socket, Tuple[object, ...]]]:
            self._register_with_iocp(listener)
            conn = self._get_accept_socket(listener.family)  # pylint: disable=assignment-from-no-return
            ov = _overlapped.Overlapped(_winapi.NULL)
            ov.AcceptEx(listener.fileno(), conn.fileno())

            def finish_accept(
                trans: object, key: socket.socket, ov: _overlapped.Overlapped
            ) -> Tuple[socket.socket, object]:
                ov.getresult()
                # Use SO_UPDATE_ACCEPT_CONTEXT so getsockname() etc work.
                buf = struct.pack("@P", listener.fileno())
                conn.setsockopt(socket.SOL_SOCKET, _overlapped.SO_UPDATE_ACCEPT_CONTEXT, buf)
                conn.settimeout(listener.gettimeout())
                return conn, conn.getpeername()

            async def accept_coro(self: ChiaProactor, future: asyncio.Future[object], conn: socket.socket) -> None:
                # Coroutine closing the accept socket if the future is cancelled
                try:
                    await future
                except asyncio.CancelledError:
                    conn.close()
                    raise
                except WindowsError as exc:  # pylint: disable=E0602
                    # https://github.com/python/cpython/issues/93821#issuecomment-1157945855
                    if exc.winerror not in (_winapi.ERROR_NETNAME_DELETED, _winapi.ERROR_OPERATION_ABORTED):
                        raise

            future = self._register(ov, listener, finish_accept)  # pylint: disable=assignment-from-no-return
            coro = accept_coro(self, future, conn)
            asyncio.ensure_future(coro, loop=self._loop)
            return future

        def accept(self, listener: socket.socket) -> asyncio.Future[Tuple[socket.socket, Tuple[object, ...]]]:
            coro = self._chia_accept_loop(listener)
            return asyncio.ensure_future(coro)

    class ChiaProactorEventLoop(ProactorEventLoop):
        # Ignoring lack of typing (via Any) since we are passing through and also never
        # call this ourselves.  There may be a good solution if needed in the future.
        # It would be better to use a real ignore since then we would get a complaint
        # if we were to start calling this but we can not do that since this is
        # platform dependent code and running mypy on other platforms will complain
        # about the ignore being unused.
        async def create_server(self, *args: Any, **kwargs: Any) -> PausableServer:
            return await _chia_create_server(super(), *args, **kwargs)

        def __init__(self) -> None:
            proactor = ChiaProactor()
            super().__init__(proactor=proactor)

        def enable_connections(self) -> None:
            self._proactor.enable_connections()

        def disable_connections(self) -> None:
            self._proactor.disable_connections()


class ChiaPolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        # overriding https://github.com/python/cpython/blob/v3.11.0/Lib/asyncio/events.py#L689-L695
        if sys.platform == "win32":
            if sys.version_info >= (3, 8):
                # https://docs.python.org/3.11/library/asyncio-policy.html#asyncio.DefaultEventLoopPolicy
                # Changed in version 3.8: On Windows, ProactorEventLoop is now used by default.
                loop_factory = ChiaProactorEventLoop
            else:
                # separate condition so coverage can report when this is no longer used
                loop_factory = ChiaSelectorEventLoop
        else:
            loop_factory = ChiaSelectorEventLoop

        return loop_factory()


def set_chia_policy(connection_limit: int) -> None:
    global global_max_concurrent_connections
    # Add "+100" to the desired peer count as a safety margin.
    global_max_concurrent_connections = connection_limit + 100
    asyncio.set_event_loop_policy(ChiaPolicy())
