from __future__ import annotations

import asyncio
import sys
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chia._tests.util.tcp_proxy import (
    BandwidthThrottle,
    TCPProxy,
    ThrottleConfig,
    proxy_connection,
    tcp_proxy,
)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="temporarily skip util tcp_proxy tests on Windows")


class TestThrottleConfig:
    """Test ThrottleConfig validation."""

    def test_negative_upload_bytes_per_sec(self) -> None:
        """Test that negative upload_bytes_per_sec raises ValueError (covers line 32)."""
        with pytest.raises(ValueError, match="upload_bytes_per_sec must be non-negative"):
            ThrottleConfig(upload_bytes_per_sec=-1)

    def test_negative_download_bytes_per_sec(self) -> None:
        """Test that negative download_bytes_per_sec raises ValueError (covers line 34)."""
        with pytest.raises(ValueError, match="download_bytes_per_sec must be non-negative"):
            ThrottleConfig(download_bytes_per_sec=-1)

    def test_negative_latency_ms(self) -> None:
        """Test that negative latency_ms raises ValueError (covers line 36)."""
        with pytest.raises(ValueError, match="latency_ms must be non-negative"):
            ThrottleConfig(latency_ms=-1.0)

    def test_valid_config(self) -> None:
        """Test that valid configuration works."""
        config = ThrottleConfig(
            upload_bytes_per_sec=100_000,
            download_bytes_per_sec=50_000,
            latency_ms=10.0,
        )
        assert config.upload_bytes_per_sec == 100_000
        assert config.download_bytes_per_sec == 50_000
        assert config.latency_ms == 10.0


class TestBandwidthThrottle:
    """Test BandwidthThrottle functionality."""

    @pytest.mark.anyio
    async def test_unlimited_bandwidth_with_latency(self) -> None:
        """Test unlimited bandwidth (bytes_per_sec=0) with latency (covers lines 52-54)."""
        throttle = BandwidthThrottle(bytes_per_sec=0, latency_ms=50.0)
        start_time = asyncio.get_event_loop().time()
        await throttle.wait_for_bandwidth(1000)
        elapsed = asyncio.get_event_loop().time() - start_time
        # Should wait for latency (50ms = 0.05s)
        assert elapsed >= 0.04  # Allow some tolerance
        assert elapsed < 0.1  # Should not take too long

    @pytest.mark.anyio
    async def test_unlimited_bandwidth_without_latency(self) -> None:
        """Test unlimited bandwidth (bytes_per_sec=0) without latency."""
        throttle = BandwidthThrottle(bytes_per_sec=0, latency_ms=0.0)
        start_time = asyncio.get_event_loop().time()
        await throttle.wait_for_bandwidth(1000)
        elapsed = asyncio.get_event_loop().time() - start_time
        # Should return immediately
        assert elapsed < 0.01

    @pytest.mark.anyio
    async def test_latency_application(self) -> None:
        """Test that latency is applied after bandwidth wait (covers line 79)."""
        throttle = BandwidthThrottle(bytes_per_sec=1000, latency_ms=20.0)
        # First call should apply latency
        start_time = asyncio.get_event_loop().time()
        await throttle.wait_for_bandwidth(100)
        elapsed = asyncio.get_event_loop().time() - start_time
        # Should include latency (20ms = 0.02s) plus some bandwidth wait
        # On CI, timing can be less precise, so allow more tolerance
        assert elapsed >= 0.015  # Allow some tolerance
        assert elapsed < 0.2  # Should not take too long (increased for CI timing variations)

    @pytest.mark.anyio
    async def test_limited_bandwidth_waits(self) -> None:
        """Test wait_for_bandwidth when bytes_allowed < num_bytes (covers lines 68-73)."""
        throttle = BandwidthThrottle(bytes_per_sec=1000, latency_ms=0.0)
        start_time = asyncio.get_event_loop().time()
        # Request more than initial allowance; should wait ~0.1s for 100 bytes at 1000 B/s
        await throttle.wait_for_bandwidth(100)
        elapsed = asyncio.get_event_loop().time() - start_time
        assert elapsed >= 0.05
        assert elapsed < 0.3

    @pytest.mark.anyio
    async def test_limited_bandwidth_uses_allowance(self) -> None:
        """Test wait_for_bandwidth when bytes_allowed >= num_bytes (covers lines 74-75)."""
        throttle = BandwidthThrottle(bytes_per_sec=1_000_000, latency_ms=0.0)
        # First call replenishes and uses allowance
        await throttle.wait_for_bandwidth(100)
        # Second call soon after should use remaining allowance (no wait)
        start_time = asyncio.get_event_loop().time()
        await throttle.wait_for_bandwidth(100)
        elapsed = asyncio.get_event_loop().time() - start_time
        assert elapsed < 0.05  # Should not wait

    @pytest.mark.anyio
    async def test_bandwidth_allowance_branch_line_75(self) -> None:
        """Test wait_for_bandwidth else branch: bytes_allowed >= num_bytes (covers line 75)."""
        # Ensure elapsed > 0 so replenish gives allowance; then we take else (line 75)
        throttle = BandwidthThrottle(bytes_per_sec=10_000_000, latency_ms=0.0)
        await asyncio.sleep(0.001)  # So elapsed is positive and bytes_allowed gets replenished
        await throttle.wait_for_bandwidth(100)  # bytes_allowed >= 100 -> else branch (line 75)
        assert throttle.bytes_allowed >= 0


class TestTCPProxy:
    """Test TCPProxy class."""

    def test_init_default_config(self, self_hostname: str) -> None:
        """Test TCPProxy with config=None uses default ThrottleConfig (covers lines 199-206)."""
        proxy = TCPProxy(
            listen_host=self_hostname,
            listen_port=0,
            server_host=self_hostname,
            server_port=8444,
            config=None,
        )
        assert proxy.config is not None
        assert proxy.config.upload_bytes_per_sec == 187_500  # DEFAULT_BANDWIDTH_BYTES_PER_SEC
        assert proxy.server is None
        assert proxy._actual_port is None

    @pytest.mark.anyio
    async def test_proxy_port_property_fallback(self, self_hostname: str) -> None:
        """Test proxy_port property fallback when _actual_port is None (covers lines 213-218)."""
        proxy = TCPProxy(
            listen_host=self_hostname,
            listen_port=0,
            server_host=self_hostname,
            server_port=8444,
        )
        # Start the proxy
        port = await proxy.start()
        assert port > 0

        # Clear _actual_port to test fallback
        proxy._actual_port = None

        # Should still work by reading from server.sockets
        proxy_port = proxy.proxy_port
        assert proxy_port == port

        await proxy.stop()

    @pytest.mark.anyio
    async def test_proxy_port_raises_when_not_started(self, self_hostname: str) -> None:
        """Test that proxy_port raises RuntimeError when proxy not started."""
        proxy = TCPProxy(
            listen_host=self_hostname,
            listen_port=0,
            server_host=self_hostname,
            server_port=8444,
        )
        # Don't start the proxy
        with pytest.raises(RuntimeError, match="Proxy not started or no socket available"):
            _ = proxy.proxy_port

    @pytest.mark.anyio
    async def test_start_raises_when_no_sockets(self, self_hostname: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that start raises RuntimeError when no sockets available (covers line 255)."""
        proxy = TCPProxy(
            listen_host=self_hostname,
            listen_port=0,
            server_host=self_hostname,
            server_port=8444,
        )

        # Mock asyncio.start_server to return a server with no sockets
        async def mock_start_server(*args: object, **kwargs: object) -> asyncio.Server:
            class MockServer:
                @property
                def sockets(self) -> list[object]:
                    return []  # No sockets

            return MockServer()  # type: ignore[return-value]

        monkeypatch.setattr(asyncio, "start_server", mock_start_server)

        with pytest.raises(RuntimeError, match="Server started but no sockets available"):
            await proxy.start()

    @pytest.mark.anyio
    async def test_context_manager(self, self_hostname: str) -> None:
        """Test TCPProxy as async context manager (covers lines 266-267, 276)."""
        async with TCPProxy(
            listen_host=self_hostname,
            listen_port=0,
            server_host=self_hostname,
            server_port=8444,
        ) as proxy:
            # Should be started
            assert proxy.server is not None
            port = proxy.proxy_port
            assert port > 0

        # Should be stopped after context exit
        # The server should be closed - check that it's either None or has no sockets
        # On some systems, the server object may persist but be closed
        if proxy.server is not None:
            # Server object exists but should be closed (no sockets)
            assert not proxy.server.sockets, "Server should be closed (no sockets)"
        else:
            # Server is None, which is also valid
            assert proxy.server is None  # pragma: no cover - platform-dependent

    @pytest.mark.anyio
    async def test_tcp_proxy_context_manager_function(self, self_hostname: str) -> None:
        """Test tcp_proxy context manager function."""
        async with tcp_proxy(
            listen_host=self_hostname,
            listen_port=0,
            server_host=self_hostname,
            server_port=8444,
        ) as proxy:
            # Should be started
            assert proxy.server is not None
            port = proxy.proxy_port
            assert port > 0

        # Should be stopped after context exit
        # The server should be closed - check that it's either None or has no sockets
        # On some systems, the server object may persist but be closed
        if proxy.server is not None:
            # Server object exists but should be closed (no sockets)
            assert not proxy.server.sockets, "Server should be closed (no sockets)"
        else:
            # Server is None, which is also valid
            assert proxy.server is None  # pragma: no cover - platform-dependent


class TestProxyConnectionUnit:
    """Unit tests for proxy_connection with mocked streams (no real sockets)."""

    @pytest.mark.anyio
    async def test_proxy_connection_with_mocked_streams(self) -> None:
        """Run proxy_connection with mocked reader/writer to cover 90-185 without socket bind."""
        # Client side mocks
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_reader.read = AsyncMock(return_value=b"")  # No data -> loops exit

        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        client_writer.get_extra_info = MagicMock(return_value=None)  # Skip socket options
        client_writer.write = MagicMock()
        client_writer.drain = AsyncMock()
        client_writer.close = MagicMock()
        client_writer.wait_closed = AsyncMock()

        # Server side mocks (returned by open_connection)
        server_reader = AsyncMock(spec=asyncio.StreamReader)
        server_reader.read = AsyncMock(return_value=b"")

        server_writer = AsyncMock(spec=asyncio.StreamWriter)
        server_writer.get_extra_info = MagicMock(return_value=None)
        server_writer.write = MagicMock()
        server_writer.drain = AsyncMock()
        server_writer.close = MagicMock()
        server_writer.wait_closed = AsyncMock()

        config = ThrottleConfig(upload_bytes_per_sec=1000, download_bytes_per_sec=1000)

        with patch(
            "chia._tests.util.tcp_proxy.asyncio.open_connection", AsyncMock(return_value=(server_reader, server_writer))
        ):
            await proxy_connection(
                client_reader,
                client_writer,
                "127.0.0.1",
                9999,
                config,
            )

        # Both forward loops ran and exited (read returned b"")
        assert client_reader.read.called
        assert server_reader.read.called
        # close() may be called from forward_server_to_client finally and outer finally
        assert client_writer.close.call_count >= 1
        assert client_writer.wait_closed.call_count >= 1

    @pytest.mark.anyio
    async def test_proxy_connection_forward_exception_paths(self) -> None:
        """Cover exception and finally in forward tasks (lines 135-139, 145-146, 155-159, 165-166)."""
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_reader.read = AsyncMock(side_effect=ConnectionResetError("test"))  # Raises -> except + finally

        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        client_writer.get_extra_info = MagicMock(return_value=None)
        client_writer.write = MagicMock()
        client_writer.drain = AsyncMock()
        client_writer.close = MagicMock()
        client_writer.wait_closed = AsyncMock()

        server_reader = AsyncMock(spec=asyncio.StreamReader)
        server_reader.read = AsyncMock(side_effect=ConnectionResetError("test"))  # Raises -> except + finally

        server_writer = AsyncMock(spec=asyncio.StreamWriter)
        server_writer.get_extra_info = MagicMock(return_value=None)
        server_writer.write = MagicMock()
        server_writer.drain = AsyncMock()
        server_writer.close = MagicMock()
        server_writer.wait_closed = AsyncMock()

        config = ThrottleConfig(upload_bytes_per_sec=1000, download_bytes_per_sec=1000)

        with patch(
            "chia._tests.util.tcp_proxy.asyncio.open_connection", AsyncMock(return_value=(server_reader, server_writer))
        ):
            await proxy_connection(
                client_reader,
                client_writer,
                "127.0.0.1",
                9999,
                config,
            )

        # Exception paths and finally blocks ran (close/wait_closed called)
        assert server_writer.close.called
        assert client_writer.close.called

    @pytest.mark.anyio
    async def test_proxy_connection_forward_write_drain_and_finally_exception(self) -> None:
        """Cover write/drain (135-136, 145-146) and finally except (155-157)."""
        # Client: return data once so we do write/drain (135-136), then raise so we hit except (137)
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_reader.read = AsyncMock(side_effect=[b"x", ConnectionResetError("test")])

        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        client_writer.get_extra_info = MagicMock(return_value=None)
        client_writer.write = MagicMock()
        client_writer.drain = AsyncMock()
        client_writer.close = MagicMock()
        # forward_server_to_client finally: wait_closed raises -> except (157)
        client_writer.wait_closed = AsyncMock(side_effect=OSError("closed"))

        # Server: data once (write/drain 145-146), then raise (except 159, finally 155-157)
        server_reader = AsyncMock(spec=asyncio.StreamReader)
        server_reader.read = AsyncMock(side_effect=[b"y", ConnectionResetError("test")])

        server_writer = AsyncMock(spec=asyncio.StreamWriter)
        server_writer.get_extra_info = MagicMock(return_value=None)
        server_writer.write = MagicMock()
        server_writer.drain = AsyncMock()
        server_writer.close = MagicMock()
        server_writer.wait_closed = AsyncMock()

        config = ThrottleConfig(upload_bytes_per_sec=1000, download_bytes_per_sec=1000)

        with patch(
            "chia._tests.util.tcp_proxy.asyncio.open_connection", AsyncMock(return_value=(server_reader, server_writer))
        ):
            await proxy_connection(
                client_reader,
                client_writer,
                "127.0.0.1",
                9999,
                config,
            )

        # write/drain were called (135-136, 145-146)
        server_writer.write.assert_called_once_with(b"x")
        client_writer.write.assert_called_once_with(b"y")
        # finally ran; client_writer.wait_closed raised -> except (157)
        assert client_writer.close.called
        assert client_writer.wait_closed.called

    @pytest.mark.anyio
    async def test_proxy_connection_forward_client_to_server_finally_exception(self) -> None:
        """Cover forward_client_to_server finally except (lines 145-146): server_writer.wait_closed raises."""
        # Client sends one chunk then EOF so forward_client_to_server enters finally (close/wait_closed)
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_reader.read = AsyncMock(side_effect=[b"x", b""])

        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        client_writer.get_extra_info = MagicMock(return_value=None)
        client_writer.write = MagicMock()
        client_writer.drain = AsyncMock()
        client_writer.close = MagicMock()
        client_writer.wait_closed = AsyncMock()

        # Server exits immediately so only forward_client_to_server does work
        server_reader = AsyncMock(spec=asyncio.StreamReader)
        server_reader.read = AsyncMock(return_value=b"")

        server_writer = AsyncMock(spec=asyncio.StreamWriter)
        server_writer.get_extra_info = MagicMock(return_value=None)
        server_writer.write = MagicMock()
        server_writer.drain = AsyncMock()
        server_writer.close = MagicMock()
        server_writer.wait_closed = AsyncMock(side_effect=OSError("closed"))  # -> except Exception (145-146)

        config = ThrottleConfig(upload_bytes_per_sec=0, download_bytes_per_sec=0)

        with patch(
            "chia._tests.util.tcp_proxy.asyncio.open_connection", AsyncMock(return_value=(server_reader, server_writer))
        ):
            await proxy_connection(
                client_reader,
                client_writer,
                "127.0.0.1",
                9999,
                config,
            )

        assert server_writer.close.called
        assert server_writer.wait_closed.called

    @pytest.mark.anyio
    async def test_proxy_connection_forward_server_to_client_write_drain(self) -> None:
        """Cover forward_server_to_client write/drain (lines 155-156)."""
        # Client exits immediately so only forward_server_to_client runs with data
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_reader.read = AsyncMock(return_value=b"")

        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        client_writer.get_extra_info = MagicMock(return_value=None)
        client_writer.write = MagicMock()
        client_writer.drain = AsyncMock()
        client_writer.close = MagicMock()
        client_writer.wait_closed = AsyncMock()

        # Server returns data once so we do client_writer.write(data) and drain() (145-146), then exit
        server_reader = AsyncMock(spec=asyncio.StreamReader)
        server_reader.read = AsyncMock(side_effect=[b"from_server", b""])

        server_writer = AsyncMock(spec=asyncio.StreamWriter)
        server_writer.get_extra_info = MagicMock(return_value=None)
        server_writer.write = MagicMock()
        server_writer.drain = AsyncMock()
        server_writer.close = MagicMock()
        server_writer.wait_closed = AsyncMock()

        # Unlimited bandwidth so wait_for_bandwidth returns immediately and we hit 145-146
        config = ThrottleConfig(upload_bytes_per_sec=0, download_bytes_per_sec=0)

        with patch(
            "chia._tests.util.tcp_proxy.asyncio.open_connection", AsyncMock(return_value=(server_reader, server_writer))
        ):
            await proxy_connection(
                client_reader,
                client_writer,
                "127.0.0.1",
                9999,
                config,
            )

        # forward_server_to_client did write and drain (145-146)
        client_writer.write.assert_called_once_with(b"from_server")
        client_writer.drain.assert_called_once()

    @pytest.mark.anyio
    async def test_proxy_connection_outer_finally_exception(self) -> None:
        """Cover outer finally exception path when writer.close/wait_closed raises (lines 184-185)."""
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_reader.read = AsyncMock(return_value=b"")

        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        client_writer.get_extra_info = MagicMock(return_value=None)
        client_writer.write = MagicMock()
        client_writer.drain = AsyncMock()
        client_writer.close = MagicMock()
        client_writer.wait_closed = AsyncMock(side_effect=OSError("closed"))  # Raises in outer finally

        server_reader = AsyncMock(spec=asyncio.StreamReader)
        server_reader.read = AsyncMock(return_value=b"")

        server_writer = AsyncMock(spec=asyncio.StreamWriter)
        server_writer.get_extra_info = MagicMock(return_value=None)
        server_writer.write = MagicMock()
        server_writer.drain = AsyncMock()
        server_writer.close = MagicMock()
        server_writer.wait_closed = AsyncMock()

        config = ThrottleConfig(upload_bytes_per_sec=1000, download_bytes_per_sec=1000)

        with patch(
            "chia._tests.util.tcp_proxy.asyncio.open_connection", AsyncMock(return_value=(server_reader, server_writer))
        ):
            await proxy_connection(
                client_reader,
                client_writer,
                "127.0.0.1",
                9999,
                config,
            )
        # Outer finally ran; exception from wait_closed was caught (lines 184-185)

    @pytest.mark.anyio
    async def test_proxy_connection_forward_client_to_server_finally_server_writer_falsy(self) -> None:
        """Cover branch 141->exit: forward_client_to_server finally when server_writer is falsy."""
        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_reader.read = AsyncMock(return_value=b"")

        client_writer = AsyncMock(spec=asyncio.StreamWriter)
        client_writer.get_extra_info = MagicMock(return_value=None)
        client_writer.write = MagicMock()
        client_writer.drain = AsyncMock()
        client_writer.close = MagicMock()
        client_writer.wait_closed = AsyncMock()

        server_reader = AsyncMock(spec=asyncio.StreamReader)
        server_reader.read = AsyncMock(return_value=b"")

        # open_connection returns (server_reader, None) so server_writer is falsy -> 141->exit
        with patch(
            "chia._tests.util.tcp_proxy.asyncio.open_connection",
            AsyncMock(return_value=(server_reader, None)),
        ):
            await proxy_connection(
                client_reader,
                client_writer,
                "127.0.0.1",
                9999,
                ThrottleConfig(upload_bytes_per_sec=0, download_bytes_per_sec=0),
            )

    @pytest.mark.anyio
    async def test_proxy_connection_forward_server_to_client_finally_client_writer_falsy(self) -> None:
        """Cover branch 161->exit: forward_server_to_client finally when client_writer is falsy."""

        class FalsyWriter:
            def __bool__(self) -> bool:
                return False

            def get_extra_info(self, key: str) -> None:
                return None  # pragma: no cover

            def write(self, data: bytes) -> None:
                pass  # pragma: no cover

            async def drain(self) -> None:
                pass  # pragma: no cover

            def close(self) -> None:
                pass  # pragma: no cover

            async def wait_closed(self) -> None:
                pass  # pragma: no cover

        client_reader = AsyncMock(spec=asyncio.StreamReader)
        client_reader.read = AsyncMock(return_value=b"")

        server_reader = AsyncMock(spec=asyncio.StreamReader)
        server_reader.read = AsyncMock(return_value=b"")

        server_writer = AsyncMock(spec=asyncio.StreamWriter)
        server_writer.get_extra_info = MagicMock(return_value=None)
        server_writer.write = MagicMock()
        server_writer.drain = AsyncMock()
        server_writer.close = MagicMock()
        server_writer.wait_closed = AsyncMock()

        with patch(
            "chia._tests.util.tcp_proxy.asyncio.open_connection", AsyncMock(return_value=(server_reader, server_writer))
        ):
            await proxy_connection(
                client_reader,
                cast(asyncio.StreamWriter, FalsyWriter()),
                "127.0.0.1",
                9999,
                ThrottleConfig(upload_bytes_per_sec=0, download_bytes_per_sec=0),
            )


class TestTCPProxyBranches:
    """Cover TCPProxy branches: proxy_port when sockets empty (215->218), start() when sockets empty (259->exit)."""

    @pytest.mark.anyio
    async def test_proxy_port_raises_when_no_sockets(self, self_hostname: str) -> None:
        """Cover branch 215->218: proxy_port when server.sockets is empty."""
        proxy = TCPProxy(
            listen_host=self_hostname,
            listen_port=0,
            server_host=self_hostname,
            server_port=9999,
        )
        proxy.server = MagicMock(spec=asyncio.Server)
        proxy.server.sockets = []

        with pytest.raises(RuntimeError, match="Proxy not started or no socket available"):
            _ = proxy.proxy_port

    @pytest.mark.anyio
    async def test_start_raises_when_server_has_no_sockets(self, self_hostname: str) -> None:
        """Cover branch 259->exit: start() when start_server returns server with no sockets."""
        proxy = TCPProxy(
            listen_host=self_hostname,
            listen_port=0,
            server_host=self_hostname,
            server_port=9999,
        )

        async def mock_start_server(*args: object, **kwargs: object) -> MagicMock:
            server = MagicMock(spec=asyncio.Server)
            server.sockets = []
            return server

        with patch("chia._tests.util.tcp_proxy.asyncio.start_server", side_effect=mock_start_server):
            with pytest.raises(RuntimeError, match="Server started but no sockets available"):
                await proxy.start()


class TestHandleClientErrorPath:
    """Cover handle_client exception and finally (lines 229-230)."""

    @pytest.mark.anyio
    async def test_handle_client_exception_and_finally(self, self_hostname: str) -> None:
        """When proxy_connection raises, handle_client catches and logs (covers 229-230)."""
        captured: list[object] = []

        async def capture_start_server(handler: object, *args: object, **kwargs: object) -> asyncio.Server:
            captured.append(handler)
            # Return a mock server so start() completes
            server = MagicMock(spec=asyncio.Server)
            server.sockets = [MagicMock()]
            server.sockets[0].getsockname = MagicMock(return_value=("127.0.0.1", 12345))
            server.close = MagicMock()
            server.wait_closed = AsyncMock()
            return server

        proxy = TCPProxy(
            listen_host=self_hostname,
            listen_port=0,
            server_host=self_hostname,
            server_port=99999,
        )

        with patch("chia._tests.util.tcp_proxy.asyncio.start_server", side_effect=capture_start_server):
            await proxy.start()

        assert len(captured) == 1
        handle_client = captured[0]
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.get_extra_info = MagicMock(return_value=None)

        with patch("chia._tests.util.tcp_proxy.proxy_connection", AsyncMock(side_effect=OSError("connection failed"))):
            await handle_client(reader, writer)  # type: ignore[operator]

        await proxy.stop()


class TestProxyConnectionErrorHandling:
    """Test error handling in proxy_connection function."""

    @pytest.mark.anyio
    async def test_forward_client_to_server_exception_handling(
        self, self_hostname: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test exception handling in forward_client_to_server (covers lines 138-139, 145-146)."""

        # Create a simple echo server (avoid wait_closed() - can raise in selector callback when peer resets)
        async def handle_echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(100)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                # Expected when connection is reset
                pass  # pragma: no cover
            finally:
                try:
                    writer.close()
                except Exception:
                    pass  # pragma: no cover
                # Do not await writer.wait_closed() - can raise in selector callback when peer resets

        echo_server = await asyncio.start_server(handle_echo, self_hostname, 0)
        echo_port = echo_server.sockets[0].getsockname()[1]

        try:
            # Create proxy
            async with tcp_proxy(
                listen_host=self_hostname,
                listen_port=0,
                server_host=self_hostname,
                server_port=echo_port,
            ) as proxy:
                proxy_port = proxy.proxy_port

                # Connect client to proxy
                _client_reader, client_writer = await asyncio.open_connection(self_hostname, proxy_port)

                # Send data so echo server handle_echo runs the loop body (write/drain) before we close
                try:
                    client_writer.write(b"test data")
                    await client_writer.drain()
                except (ConnectionResetError, BrokenPipeError, OSError):
                    pass  # pragma: no cover

                # Close the server connection to trigger exception in forward_client_to_server
                echo_server.close()
                await echo_server.wait_closed()

                # Try to write again - this should trigger ConnectionResetError
                try:
                    client_writer.write(b"more data")
                    await client_writer.drain()
                except (ConnectionResetError, BrokenPipeError, OSError):
                    pass  # pragma: no cover

                # Wait a bit for the exception to be handled by the proxy
                await asyncio.sleep(0.2)

                # Clean up (may raise if connection already reset)
                try:
                    client_writer.close()
                    await client_writer.wait_closed()
                except (ConnectionResetError, BrokenPipeError, OSError):
                    pass  # pragma: no cover

        finally:
            echo_server.close()
            await echo_server.wait_closed()

    @pytest.mark.anyio
    async def test_forward_server_to_client_exception_handling(
        self, self_hostname: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test exception handling in forward_server_to_client (covers lines 158-159, 165-166)."""

        # Create a simple echo server (catch connection errors - client close can cause read() to raise)
        async def handle_echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    try:
                        data = await reader.read(100)
                    except (ConnectionResetError, BrokenPipeError, OSError):
                        break  # pragma: no cover
                    if not data:
                        break  # pragma: no cover
                    try:
                        writer.write(data)
                        await writer.drain()
                    except (ConnectionResetError, BrokenPipeError, OSError):
                        break  # pragma: no cover
            finally:
                try:
                    writer.close()
                except Exception:
                    pass  # pragma: no cover
                # Do not await writer.wait_closed() - can raise in selector callback when peer resets

        echo_server = await asyncio.start_server(handle_echo, self_hostname, 0)
        echo_port = echo_server.sockets[0].getsockname()[1]

        try:
            # Create proxy
            async with tcp_proxy(
                listen_host=self_hostname,
                listen_port=0,
                server_host=self_hostname,
                server_port=echo_port,
            ) as proxy:
                proxy_port = proxy.proxy_port

                # Connect client to proxy
                _client_reader, client_writer = await asyncio.open_connection(self_hostname, proxy_port)

                # Send data so echo server handle_echo runs the loop body (write/drain) before we close
                try:
                    client_writer.write(b"hello")
                    await client_writer.drain()
                except (ConnectionResetError, BrokenPipeError, OSError):
                    pass  # pragma: no cover

                # Close client connection to trigger exception in forward_server_to_client
                try:
                    client_writer.close()
                    await client_writer.wait_closed()
                except (ConnectionResetError, BrokenPipeError, OSError):
                    pass  # pragma: no cover

                # Wait a bit for the exception to be handled by the proxy
                await asyncio.sleep(0.2)

        finally:
            echo_server.close()
            await echo_server.wait_closed()

    @pytest.mark.anyio
    async def test_proxy_connection_exception_handling(self, self_hostname: str) -> None:
        """Test exception handling in proxy_connection (covers lines 175-176, 184-185)."""
        # Create proxy pointing to non-existent server
        async with tcp_proxy(
            listen_host=self_hostname,
            listen_port=0,
            server_host=self_hostname,
            server_port=99999,  # Non-existent port
        ) as proxy:
            proxy_port = proxy.proxy_port

            # Try to connect - should fail but handle exception gracefully
            try:
                _client_reader, client_writer = await asyncio.wait_for(
                    asyncio.open_connection(self_hostname, proxy_port), timeout=0.5
                )
                # If connection succeeds (unlikely), try to write
                # This will trigger an error when proxy tries to connect to non-existent server
                client_writer.write(b"test")
                await client_writer.drain()
                await asyncio.sleep(0.1)  # Give time for exception handling
                client_writer.close()
                await client_writer.wait_closed()
            except (ConnectionRefusedError, OSError, asyncio.TimeoutError, ConnectionResetError):
                # Expected - connection should fail or be reset
                pass

    @pytest.mark.anyio
    async def test_proxy_connection_write_drain_when_connected(self, self_hostname: str) -> None:
        """Cover connection-succeeds path: connect to proxy with real backend, then write/drain."""
        # Minimal server that accepts and does nothing (so proxy can connect to backend)
        dummy_server = await asyncio.start_server(
            lambda r, w: None,
            self_hostname,
            0,
        )
        backend_port = dummy_server.sockets[0].getsockname()[1]

        try:
            async with tcp_proxy(
                listen_host=self_hostname,
                listen_port=0,
                server_host=self_hostname,
                server_port=backend_port,
            ) as proxy:
                proxy_port = proxy.proxy_port

                _client_reader, client_writer = await asyncio.wait_for(
                    asyncio.open_connection(self_hostname, proxy_port),
                    timeout=2.0,
                )
                try:
                    client_writer.write(b"test")
                    await client_writer.drain()
                    await asyncio.sleep(0.1)
                finally:
                    try:
                        client_writer.close()
                        await client_writer.wait_closed()
                    except (ConnectionResetError, BrokenPipeError, OSError):
                        pass
        finally:
            dummy_server.close()
            await dummy_server.wait_closed()

    @pytest.mark.anyio
    async def test_handle_client_exception_handling(self, self_hostname: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test exception handling in handle_client (covers lines 229-230)."""
        # Create a server that will cause errors
        error_server = await asyncio.start_server(
            lambda r, w: None,  # Handler that does nothing
            self_hostname,
            0,
        )
        error_port = error_server.sockets[0].getsockname()[1]

        try:
            # Create proxy
            async with tcp_proxy(
                listen_host=self_hostname,
                listen_port=0,
                server_host=self_hostname,
                server_port=error_port,
            ) as proxy:
                proxy_port = proxy.proxy_port

                # Connect and immediately close to trigger exception handling
                _client_reader, client_writer = await asyncio.open_connection(self_hostname, proxy_port)
                client_writer.close()
                await client_writer.wait_closed()

                # Wait for exception to be handled
                await asyncio.sleep(0.1)

        finally:
            error_server.close()
            await error_server.wait_closed()
