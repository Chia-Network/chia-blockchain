import asyncio
from blspy import PrivateKey
from src.protocol.protocol import ChiaProtocol
from src.types.plotter_api import CreatePlot, NewChallenge


async def main():
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

    on_con_lost = loop.create_future()

    transport, protocol = await loop.create_connection(
        lambda: ChiaProtocol(on_con_lost, loop, lambda x: x),
        '127.0.0.1', 8888)

    ppk = PrivateKey.from_seed(b"123").get_public_key()
    await protocol.send("create_plot", CreatePlot(16, ppk, b"myplot_1.dat"))
    # protocol.send("create_plot", CreatePlot(17, ppk, b"myplot_2.dat"))
    await protocol.send("new_challenge", NewChallenge(bytes([77]*32)))

    # Wait until the protocol signals that the connection
    # is lost and close the transport.
    try:
        await on_con_lost
    finally:
        transport.close()


asyncio.run(main())
