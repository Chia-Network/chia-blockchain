from __future__ import annotations

import asyncio

import pytest

from chia._tests.util.tcp_proxy import (
    BandwidthThrottle,
    TCPProxy,
    ThrottleConfig,
    tcp_proxy,
)


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
        assert elapsed >= 0.015  # Allow some tolerance
        assert elapsed < 0.1  # Should not take too long


class TestTCPProxy:
    """Test TCPProxy class."""

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
        assert proxy.server is None

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
        assert proxy.server is None


class TestProxyConnectionErrorHandling:
    """Test error handling in proxy_connection function."""

    @pytest.mark.anyio
    async def test_forward_client_to_server_exception_handling(
        self, self_hostname: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test exception handling in forward_client_to_server (covers lines 138-139, 145-146)."""

        # Create a simple echo server
        async def handle_echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(100)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

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

                # Close the server connection to trigger exception in forward_client_to_server
                echo_server.close()
                await echo_server.wait_closed()

                # Try to write data - this should trigger ConnectionResetError
                client_writer.write(b"test data")
                await client_writer.drain()

                # Wait a bit for the exception to be handled
                await asyncio.sleep(0.1)

                # Clean up
                client_writer.close()
                await client_writer.wait_closed()

        finally:
            echo_server.close()
            await echo_server.wait_closed()

    @pytest.mark.anyio
    async def test_forward_server_to_client_exception_handling(
        self, self_hostname: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test exception handling in forward_server_to_client (covers lines 158-159, 165-166)."""

        # Create a simple echo server
        async def handle_echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await reader.read(100)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

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

                # Close client connection to trigger exception in forward_server_to_client
                client_writer.close()
                await client_writer.wait_closed()

                # Wait a bit for the exception to be handled
                await asyncio.sleep(0.1)

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
