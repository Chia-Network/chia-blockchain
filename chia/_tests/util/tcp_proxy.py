from __future__ import annotations

import asyncio
import logging
import socket
import struct
import time
import types
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Self

log = logging.getLogger(__name__)

# Default to 0.5 Mbps symmetrical (500,000 bits/sec = 62,500 bytes/sec)
DEFAULT_BANDWIDTH_BYTES_PER_SEC = 62_500


@dataclass
class ThrottleConfig:
    """Configuration for bandwidth throttling."""

    upload_bytes_per_sec: int = DEFAULT_BANDWIDTH_BYTES_PER_SEC
    download_bytes_per_sec: int = DEFAULT_BANDWIDTH_BYTES_PER_SEC
    latency_ms: float = 0.0  # Additional latency in milliseconds

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.upload_bytes_per_sec < 0:
            raise ValueError("upload_bytes_per_sec must be non-negative")
        if self.download_bytes_per_sec < 0:
            raise ValueError("download_bytes_per_sec must be non-negative")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")


class BandwidthThrottle:
    """Throttles bandwidth for a single direction of data flow."""

    def __init__(self, bytes_per_sec: int, latency_ms: float = 0.0) -> None:
        self.bytes_per_sec = bytes_per_sec
        self.latency_sec = latency_ms / 1000.0
        self.bytes_allowed = 0.0
        self.last_update = time.monotonic()

    async def wait_for_bandwidth(self, num_bytes: int) -> None:
        """Wait until enough bandwidth is available for the given number of bytes."""
        if self.bytes_per_sec == 0:
            # Unlimited bandwidth
            if self.latency_sec > 0:
                await asyncio.sleep(self.latency_sec)
            return

        now = time.monotonic()
        elapsed = now - self.last_update

        # Replenish bandwidth based on elapsed time
        self.bytes_allowed += elapsed * self.bytes_per_sec
        self.last_update = now

        # Cap at reasonable limit (2x the rate to allow bursts)
        max_allowance = self.bytes_per_sec * 2
        self.bytes_allowed = min(self.bytes_allowed, max_allowance)

        # Wait if we don't have enough bandwidth
        if self.bytes_allowed < num_bytes:
            needed = num_bytes - self.bytes_allowed
            wait_time = needed / self.bytes_per_sec
            await asyncio.sleep(wait_time)
            self.bytes_allowed = 0.0
            self.last_update = time.monotonic()
        else:
            self.bytes_allowed -= num_bytes

        # Apply latency
        if self.latency_sec > 0:
            await asyncio.sleep(self.latency_sec)


async def proxy_connection(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    server_host: str,
    server_port: int,
    config: ThrottleConfig,
) -> None:
    """Proxy a single connection with bandwidth throttling."""
    server_reader: asyncio.StreamReader | None = None
    server_writer: asyncio.StreamWriter | None = None

    try:
        # Set socket options on client connection for better resource management
        client_sock = client_writer.get_extra_info("socket")
        if client_sock is not None:
            # Set TCP_NODELAY to disable Nagle's algorithm for lower latency
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # Set SO_LINGER with 0 timeout to avoid TIME_WAIT state on close
            # This sends RST instead of FIN, immediately releasing the socket
            # l_onoff=1 (enable linger), l_linger=0 (0 second timeout = immediate RST)
            client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

        # Connect to the server
        server_reader, server_writer = await asyncio.open_connection(server_host, server_port)

        # Set socket options on server connection (outbound connection)
        # This is critical to avoid ephemeral port exhaustion from TIME_WAIT sockets
        server_sock = server_writer.get_extra_info("socket")
        if server_sock is not None:
            # Set TCP_NODELAY to disable Nagle's algorithm for lower latency
            server_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # Set SO_LINGER with 0 timeout to avoid TIME_WAIT state on close
            # This is essential for the proxy to avoid exhausting ephemeral ports
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

        log.debug(f"Proxy connected to server {server_host}:{server_port}")

        # Create throttles for each direction
        # Upload: client -> server (data going to server)
        upload_throttle = BandwidthThrottle(config.upload_bytes_per_sec, config.latency_ms)
        # Download: server -> client (data coming from server)
        download_throttle = BandwidthThrottle(config.download_bytes_per_sec, config.latency_ms)

        # Chunk size for throttling (smaller = smoother throttling, larger = less overhead)
        chunk_size = 8192

        async def forward_client_to_server() -> None:
            """Forward data from client to server with upload throttling."""
            try:
                while True:
                    data = await client_reader.read(chunk_size)
                    if not data:
                        break
                    await upload_throttle.wait_for_bandwidth(len(data))
                    server_writer.write(data)
                    await server_writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError, asyncio.CancelledError):
                pass
            finally:
                if server_writer:
                    try:
                        server_writer.close()
                        await server_writer.wait_closed()
                    except Exception:
                        pass

        async def forward_server_to_client() -> None:
            """Forward data from server to client with download throttling."""
            try:
                while True:
                    data = await server_reader.read(chunk_size)
                    if not data:
                        break
                    await download_throttle.wait_for_bandwidth(len(data))
                    client_writer.write(data)
                    await client_writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError, asyncio.CancelledError):
                pass
            finally:
                if client_writer:
                    try:
                        client_writer.close()
                        await client_writer.wait_closed()
                    except Exception:
                        pass

        # Run both directions concurrently
        await asyncio.gather(
            forward_client_to_server(),
            forward_server_to_client(),
            return_exceptions=True,
        )

    except Exception as e:
        log.debug(f"Proxy connection error: {e}")
    finally:
        # Clean up
        for writer in [client_writer, server_writer]:
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass


class TCPProxy:
    """A TCP proxy that throttles bandwidth between client and server."""

    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        server_host: str,
        server_port: int,
        config: ThrottleConfig | None = None,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.server_host = server_host
        self.server_port = server_port
        self.config = config or ThrottleConfig()
        self.server: asyncio.Server | None = None
        self.server_task: asyncio.Task[None] | None = None
        self._actual_port: int | None = None

    @property
    def proxy_port(self) -> int:
        """Get the actual port the proxy is listening on."""
        if self._actual_port is not None:
            return self._actual_port
        if self.server:
            sockets = self.server.sockets
            if sockets:
                port: int = sockets[0].getsockname()[1]
                return port
        raise RuntimeError("Proxy not started or no socket available")

    async def start(self) -> int:
        """Start the proxy server. Returns the actual listen port."""

        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            """Handle a new client connection."""
            client_addr = writer.get_extra_info("peername")
            log.debug(f"Proxy accepted connection from {client_addr}")
            try:
                await proxy_connection(reader, writer, self.server_host, self.server_port, self.config)
            except Exception as e:
                log.debug(f"Error proxying connection from {client_addr}: {e}")
            finally:
                log.debug(f"Proxy closed connection from {client_addr}")

        # Use reuse_address=True to allow immediate reuse of the address/port
        # This helps with resource management and prevents "Address already in use" errors
        self.server = await asyncio.start_server(
            handle_client,
            self.listen_host,
            self.listen_port,
            reuse_address=True,
        )

        # Get the actual port (in case 0 was used for auto-assignment)
        sockets = self.server.sockets
        if sockets:
            self._actual_port = sockets[0].getsockname()[1]
            log.info(
                f"TCP proxy listening on {self.listen_host}:{self._actual_port}, "
                f"forwarding to {self.server_host}:{self.server_port}, "
                f"upload={self.config.upload_bytes_per_sec} bytes/s, "
                f"download={self.config.download_bytes_per_sec} bytes/s"
            )
            return self._actual_port
        else:
            raise RuntimeError("Server started but no sockets available")

    async def stop(self) -> None:
        """Stop the proxy server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            log.info("TCP proxy stopped")

    async def __aenter__(self) -> Self:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Async context manager exit."""
        await self.stop()


@asynccontextmanager
async def tcp_proxy(
    listen_host: str,
    listen_port: int,
    server_host: str,
    server_port: int,
    upload_bytes_per_sec: int = DEFAULT_BANDWIDTH_BYTES_PER_SEC,
    download_bytes_per_sec: int = DEFAULT_BANDWIDTH_BYTES_PER_SEC,
    latency_ms: float = 0.0,
) -> AsyncIterator[TCPProxy]:
    """Context manager for a TCP proxy with bandwidth throttling.

    Args:
        listen_host: Host to listen on (e.g., "127.0.0.1")
        listen_port: Port to listen on (0 for auto-assignment)
        server_host: Target server hostname
        server_port: Target server port
        upload_bytes_per_sec: Upload bandwidth limit (client -> server), default 0.5 Mbps (62,500 bytes/s)
        download_bytes_per_sec: Download bandwidth limit (server -> client), default 0.5 Mbps (62,500 bytes/s)
        latency_ms: Additional latency in milliseconds

    Yields:
        TCPProxy instance with the actual listen port available via proxy.proxy_port

    Example:
        # Use default 0.5 Mbps symmetrical throttling
        async with tcp_proxy("127.0.0.1", 0, "127.0.0.1", 8444) as proxy:
            proxy_port = proxy.proxy_port
            # Connect to proxy_port instead of 8444

        # Custom bandwidth (1 Mbps upload, 0.25 Mbps download)
        async with tcp_proxy(
            "127.0.0.1", 0, "127.0.0.1", 8444,
            upload_bytes_per_sec=125_000,  # 1 Mbps
            download_bytes_per_sec=31_250,  # 0.25 Mbps
        ) as proxy:
            proxy_port = proxy.proxy_port
    """
    config = ThrottleConfig(
        upload_bytes_per_sec=upload_bytes_per_sec,
        download_bytes_per_sec=download_bytes_per_sec,
        latency_ms=latency_ms,
    )
    proxy = TCPProxy(listen_host, listen_port, server_host, server_port, config)
    try:
        await proxy.start()
        yield proxy
    finally:
        await proxy.stop()
