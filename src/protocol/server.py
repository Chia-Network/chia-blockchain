import asyncio
from protocol import ChiaProtocol
from src.plotter import Plotter


async def main(api_cls):
    loop = asyncio.get_running_loop()

    on_con_lost = loop.create_future()

    server = await loop.create_server(
        lambda: ChiaProtocol(on_con_lost, loop, api_cls()),
        '127.0.0.1', 8888, start_serving=False)

    print(f'Starting {api_cls.__name__} server')

    async with server:
        await server.serve_forever()

asyncio.run(main(Plotter))
