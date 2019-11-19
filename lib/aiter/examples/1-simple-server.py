import asyncio

from aiter.server import start_server_aiter


async def main():
    server, aiter = await start_server_aiter(7777)
    async for _ in aiter:
        print(_)


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
