from __future__ import annotations

import asyncio
import inspect
import sys
import threading

from chia.server.chia_policy import ChiaSelectorEventLoop, PausableServer, _chia_create_server, set_chia_policy


def test_base_event_loop_has_methods() -> None:
    """
    `ChiaPolicy` overrides `create_server` to create and return the custom `PausableServer`
    instead of its base class `asyncio.base_events.Server`.

    This method checks asyncio's `create_server` and the constructor of asyncio's `base_events.Server`
    keep the same constant signature.

    Moreover, this checks our internal method `_chia_create_server` doesn't change signature and that our
    custom event loop's constructor uses it in the implementation (by enforcing a fixed implementation).

    Also, we check all methods needed by `PausableServer` are still present in the base classes and
    that their signature remains constant: `__init__`, `_attach`, `_detach`, `remove_reader` and `_start_serving`.
    """

    selector_event_loop = ChiaSelectorEventLoop()
    try:
        base_selector_event_loop = super(ChiaSelectorEventLoop, selector_event_loop)

        assert hasattr(base_selector_event_loop, "create_server")
        method = getattr(base_selector_event_loop, "create_server")
        assert inspect.ismethod(method)
        if sys.version_info >= (3, 11):
            expected_signature = "(protocol_factory, host=None, port=None, *, family=<AddressFamily.AF_UNSPEC: 0>, flags=<AddressInfo.AI_PASSIVE: 1>, sock=None, backlog=100, ssl=None, reuse_address=None, reuse_port=None, ssl_handshake_timeout=None, ssl_shutdown_timeout=None, start_serving=True)"  # noqa: E501
        else:
            expected_signature = "(protocol_factory, host=None, port=None, *, family=<AddressFamily.AF_UNSPEC: 0>, flags=<AddressInfo.AI_PASSIVE: 1>, sock=None, backlog=100, ssl=None, reuse_address=None, reuse_port=None, ssl_handshake_timeout=None, start_serving=True)"  # noqa: E501
        assert str(inspect.signature(method)) == expected_signature

        assert hasattr(base_selector_event_loop, "_start_serving")
        method = getattr(base_selector_event_loop, "_start_serving")
        assert inspect.ismethod(method)
        if sys.version_info >= (3, 11):
            expected_signature = "(protocol_factory, sock, sslcontext=None, server=None, backlog=100, ssl_handshake_timeout=60.0, ssl_shutdown_timeout=30.0)"  # noqa: E501
        else:
            expected_signature = (
                "(protocol_factory, sock, sslcontext=None, server=None, backlog=100, ssl_handshake_timeout=60.0)"
            )
        assert str(inspect.signature(method)) == expected_signature

        assert hasattr(base_selector_event_loop, "remove_reader")
        method = getattr(base_selector_event_loop, "remove_reader")
        assert inspect.ismethod(method)
        expected_signature = "(fd)"
        assert str(inspect.signature(method)) == expected_signature

        assert hasattr(selector_event_loop, "create_server")
        method = getattr(selector_event_loop, "create_server")
        assert inspect.ismethod(method)
        assert (
            inspect.getsource(method)
            == "    async def create_server(self, *args, **kwargs) -> PausableServer:  # type: ignore[no-untyped-def]\n        return await _chia_create_server(super(), *args, **kwargs)\n"  # noqa: E501
        )

        assert inspect.isfunction(_chia_create_server)
        expected_signature = "(cls: 'Any', protocol_factory: '_ProtocolFactory', host: 'Any', port: 'Any', *, family: 'socket.AddressFamily' = <AddressFamily.AF_UNSPEC: 0>, flags: 'socket.AddressInfo' = <AddressInfo.AI_PASSIVE: 1>, sock: 'Any' = None, backlog: 'int' = 100, ssl: '_SSLContext' = None, reuse_address: 'Optional[bool]' = None, reuse_port: 'Optional[bool]' = None, ssl_handshake_timeout: 'Optional[float]' = 30, start_serving: 'bool' = True) -> 'PausableServer'"  # noqa: E501
        assert str(inspect.signature(_chia_create_server)) == expected_signature

        class EchoProtocol(asyncio.Protocol):
            def connection_made(self, transport):  # type: ignore
                self.transport = transport

            def data_received(self, data):  # type: ignore
                self.transport.write(data)

        pausable_server = None

        def in_thread() -> None:
            async def main() -> None:
                loop = asyncio.get_event_loop()
                nonlocal pausable_server
                pausable_server = await loop.create_server(
                    EchoProtocol, host="127.0.0.1", port=8000, ssl_handshake_timeout=None, start_serving=False
                )

            set_chia_policy(connection_limit=0)
            asyncio.run(main())

        thread = threading.Thread(target=in_thread)
        thread.start()
        thread.join()

        base_server = super(PausableServer, pausable_server)

        method = getattr(base_server, "__init__")
        if sys.version_info >= (3, 11):
            expected_signature = (
                "(loop, sockets, protocol_factory, ssl_context, backlog, ssl_handshake_timeout,"
                " ssl_shutdown_timeout=None)"
            )
        else:
            expected_signature = "(loop, sockets, protocol_factory, ssl_context, backlog, ssl_handshake_timeout)"
        assert str(inspect.signature(method)) == expected_signature

        for func in ("_attach", "_detach"):
            assert hasattr(base_server, func)
            method = getattr(base_server, func)
            assert str(inspect.signature(method)) == "()"
    finally:
        selector_event_loop.close()
