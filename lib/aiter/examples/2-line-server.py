import asyncio

from aiter.server import start_server_aiter


async def stream_reader_to_line_aiter(sr):
    while True:
        r = await sr.readline()
        if len(r) == 0:
            break
        yield r


async def main():
    server, aiter = await start_server_aiter(7777)
    async for sr, sw in aiter:
        print(sr)
        line_aiter = stream_reader_to_line_aiter(sr)
        # this hack means we only accept one connection
        break

    async for line in line_aiter:
        print(line)


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
