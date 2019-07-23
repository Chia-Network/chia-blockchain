import asyncio
import secrets
from blspy import PrivateKey

from src import farmer
from src.server.server import ChiaConnection
from src.types.protocols.plotter_protocol import PlotterHandshake, NewChallenge


async def timeout_loop(client_con: ChiaConnection):
    while True:
        await asyncio.sleep(5)
        await client_con.send("new_challenge", NewChallenge(secrets.token_bytes(32)))


async def main():
    client_con = ChiaConnection(farmer)
    client_server = await client_con.open_connection('127.0.0.1', 8000)
    ppk = PrivateKey.from_seed(b"123").get_public_key()

    await client_con.send("plotter_handshake", PlotterHandshake(ppk))
    timeout = asyncio.create_task(timeout_loop(client_con))

    print("After timeout")
    await asyncio.gather(client_server, timeout)

asyncio.run(main())
