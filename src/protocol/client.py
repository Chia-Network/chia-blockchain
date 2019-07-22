import asyncio
from protocol import ChiaProtocol
from blspy import PrivateKey

async def main():
    # Get a reference to the event loop as we plan to use
    # low-level APIs.
    loop = asyncio.get_running_loop()

    on_con_lost = loop.create_future()

    transport, protocol = await loop.create_connection(
        lambda: ChiaProtocol(on_con_lost, loop, lambda x: x),
        '127.0.0.1', 8888)

    ppk = PrivateKey.from_seed(b"123").get_public_key().serialize()
    protocol.send("create_plot", 16, "myplot1.dat", ppk)
    protocol.send("create_plot", 17, "myplot2.dat", ppk)
    protocol.send("new_challenge", bytes([2]*32))

    # Wait until the protocol signals that the connection
    # is lost and close the transport.
    try:
        await on_con_lost
    finally:
        transport.close()


asyncio.run(main())