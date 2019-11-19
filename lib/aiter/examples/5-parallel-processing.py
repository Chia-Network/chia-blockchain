import asyncio
import functools

from aiter import (
    join_aiters, map_aiter
)
from aiter.server import start_server_aiter


async def handle_event(server_line_sw_tuple):
    server, line, sw = server_line_sw_tuple
    await sw.drain()
    if line == b"\n":
        sw.close()
    sw.write(line)
    if line == b"quit\n":
        server.close()
    if line == b"wait\n":
        await asyncio.sleep(5)
    return line


async def stream_reader_writer_to_line_writer_aiter(server, pair):
    sr, sw = pair
    while True:
        line = await sr.readline()
        if len(line) == 0:
            break
        yield server, line, sw


async def main():
    server, aiter = await start_server_aiter(7777)

    line_writer_aiter_aiter = map_aiter(
        functools.partial(
            stream_reader_writer_to_line_writer_aiter,
            server),
        aiter)
    line_writer_aiter = join_aiters(line_writer_aiter_aiter)
    completed_event_aiter = map_aiter(
        handle_event,
        line_writer_aiter,
        worker_count=5)

    async for line in completed_event_aiter:
        print(line)


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
