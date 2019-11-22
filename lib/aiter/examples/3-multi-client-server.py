import asyncio

from aiter import join_aiters, map_aiter
from aiter.server import start_server_aiter


async def stream_reader_writer_to_line_writer_aiter(pair):
    sr, sw = pair
    while True:
        r = await sr.readline()
        if len(r) == 0:
            break
        yield r, sw


async def main():
    server, aiter = await start_server_aiter(7777)
    line_writer_aiter_aiter = map_aiter(
        stream_reader_writer_to_line_writer_aiter,
        aiter)
    line_writer_aiter = join_aiters(line_writer_aiter_aiter)

    async for line, sw in line_writer_aiter:
        print(line)
        await sw.drain()
        if line == b"\n":
            sw.close()
        sw.write(line)
        if line == b"quit\n":
            server.close()


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
