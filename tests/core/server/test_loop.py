from __future__ import annotations

import asyncio
import contextlib
import pathlib
import random
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, List, Optional

import anyio
import pytest

from chia.server import chia_policy
from tests.core.server import serve

here = pathlib.Path(__file__).parent

# TODO: CAMPid 0945094189459712842390t591
IP = "127.0.0.1"
PORT = 8444
NUM_CLIENTS = 500
allowed_over_connections = 0 if sys.platform == "win32" else 100


@contextlib.asynccontextmanager
async def serve_in_thread(ip: str, port: int, connection_limit: int) -> AsyncIterator[ServeInThread]:
    server = ServeInThread(ip=ip, requested_port=port, connection_limit=connection_limit)
    server.start()
    # TODO: can we check when it has really started?  just make a connection?
    await asyncio.sleep(1)
    try:
        yield server
    finally:
        server.stop()


@dataclass
class Client:
    reader: Optional[asyncio.StreamReader]
    writer: Optional[asyncio.StreamWriter]

    @classmethod
    async def open(cls, ip: str, port: int) -> Client:
        try:
            reader, writer = await asyncio.open_connection(ip, port)
            return cls(reader=reader, writer=writer)
        except (TimeoutError, ConnectionResetError, ConnectionRefusedError):
            return cls(reader=None, writer=None)

    @classmethod
    @contextlib.asynccontextmanager
    async def open_several(cls, count: int, ip: str, port: int) -> AsyncIterator[List[Client]]:
        clients: List[Client] = await asyncio.gather(*(cls.open(ip=ip, port=port) for _ in range(count)))
        try:
            yield [*clients]
        finally:
            await asyncio.gather(*(client.close() for client in clients))

    async def is_alive(self) -> bool:
        if self.reader is None or self.writer is None:
            return False
        separator = b"\xff"
        n = 8
        to_send = bytes(random.randrange(255) for _ in range(n))
        try:
            with anyio.fail_after(delay=1):
                self.writer.write(to_send + separator)
                received = await self.reader.readuntil(separator=separator)
                received = received[:-1]
        except TimeoutError:
            return False

        # print(f" ==== {received=} {to_send=}")
        return received == to_send

    async def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            await self.writer.wait_closed()


@dataclass()
class ServeInThread:
    ip: str
    requested_port: int
    connection_limit: int = 25
    original_connection_limit: Optional[int] = None
    loop: Optional[asyncio.AbstractEventLoop] = None
    server_task: Optional[asyncio.Task[None]] = None
    thread: Optional[threading.Thread] = None
    thread_end_event: threading.Event = field(default_factory=threading.Event)
    port_holder: List[int] = field(default_factory=list)

    def start(self) -> None:
        self.original_connection_limit = chia_policy.global_max_concurrent_connections
        # TODO: yuck yuck, messes with a single global
        chia_policy.global_max_concurrent_connections = self.connection_limit

        self.thread = threading.Thread(target=self._run)
        self.thread.start()

    def port(self) -> int:
        [port] = self.port_holder
        return port

    def _run(self) -> None:
        # TODO: yuck yuck, messes with a single global
        asyncio.set_event_loop_policy(chia_policy.ChiaPolicy())
        asyncio.run(self.main())
        # new_loop = asyncio.new_event_loop()
        # asyncio.set_event_loop(new_loop)
        # new_loop.run_until_complete(self.main())

    async def main(self) -> None:
        self.loop = asyncio.get_event_loop()
        self.server_task = asyncio.create_task(
            serve.async_main(
                ip=self.ip,
                port=self.requested_port,
                thread_end_event=self.thread_end_event,
                port_holder=self.port_holder,
            ),
            name="server in thread",
        )
        try:
            await self.server_task
        except asyncio.CancelledError:
            pass

    def stop(self) -> None:
        # print(f" ==== cancelling {self.server_task}")
        # self.server_task.cancel()
        # print(f" ==== requested cancel of {self.server_task}")
        self.thread_end_event.set()
        if self.thread is None:
            raise Exception("trying to stop without a running thread")
        self.thread.join()

        if self.original_connection_limit is not None:
            chia_policy.global_max_concurrent_connections = self.original_connection_limit


@pytest.mark.asyncio
async def test_loop() -> None:
    print(" ==== launching serve.py")
    with subprocess.Popen(
        [sys.executable, "-m", "tests.core.server.serve"],
        encoding="utf-8",
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
    ) as serving_process:
        print(" ====           serve.py running")
        time.sleep(5)
        print(" ==== launching flood.py")
        with subprocess.Popen(
            [sys.executable, "-m", "tests.core.server.flood"],
            encoding="utf-8",
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE,
        ) as flooding_process:
            print(" ====           flood.py running")
            time.sleep(5)
            print(" ====   killing flood.py")
            flooding_process.kill()
        print(" ====           flood.py done")

        time.sleep(5)

        writer = None
        try:
            with anyio.fail_after(delay=1):
                print(" ==== attempting a single new connection")
                reader, writer = await asyncio.open_connection(IP, PORT)
                print(" ==== connection succeeded")
                post_connection_succeeded = True
        except (TimeoutError, ConnectionRefusedError):
            post_connection_succeeded = False
        finally:
            if writer is not None:
                writer.close()
                await writer.wait_closed()

        print(" ====   killing serve.py")
        # serving_process.send_signal(signal.CTRL_C_EVENT)
        # serving_process.terminate()
        output, _ = serving_process.communicate()
    print(" ====           serve.py done")

    print("\n\n ==== output:")
    print(output)

    over = []
    connection_limit = 25
    accept_loop_count_over: List[int] = []
    for line in output.splitlines():
        mark = "Total connections:"
        if mark in line:
            _, _, rest = line.partition(mark)
            count = int(rest)
            if count > connection_limit + allowed_over_connections:
                over.append(count)

        # mark = "ChiaProactor._chia_accept_loop() entering count="
        # if mark in line:
        #     _, _, rest = line.partition(mark)
        #     count = int(rest)
        #     if count > 1:
        #         accept_loop_count_over.append(count)

    assert over == [], over
    assert accept_loop_count_over == [], accept_loop_count_over
    assert "Traceback" not in output
    assert "paused accepting connections" in output
    assert post_connection_succeeded

    print(" ==== all checks passed")


# repeating in case there are races or flakes to expose
@pytest.mark.parametrize(
    argnames="repetition",
    argvalues=[x + 1 for x in range(25)],
    ids=lambda repetition: f"#{repetition}",
)
@pytest.mark.parametrize(
    # make sure the server continues to work after exceeding limits repeatedly
    argnames="cycles",
    argvalues=[1, 5],
    ids=lambda cycles: f"{cycles} cycle{'s' if cycles != 1 else ''}",
)
@pytest.mark.asyncio
async def test_limits_connections(repetition: int, cycles: int) -> None:
    ip = "127.0.0.1"
    connection_limit = 25
    connection_attempts = 1000

    async with serve_in_thread(ip=ip, port=0, connection_limit=connection_limit) as server:
        for cycle in range(cycles):
            clients: List[Client]

            async with Client.open_several(count=connection_attempts, ip=ip, port=server.port()) as clients:
                are_alive = await asyncio.gather(*(client.is_alive() for client in clients))

                connected_clients = [client for client, is_alive in zip(clients, are_alive) if is_alive]
                not_connected_clients = [client for client, is_alive in zip(clients, are_alive) if not is_alive]

            assert len(connected_clients) >= connection_limit, f"cycle={cycle}"
            assert len(connected_clients) <= connection_limit + allowed_over_connections, f"cycle={cycle}"
            assert len(not_connected_clients) <= connection_attempts - connection_limit, f"cycle={cycle}"
            assert (
                len(not_connected_clients) >= connection_attempts - connection_limit - allowed_over_connections
            ), f"cycle={cycle}"
