import asyncio
import secrets
import logging

from src import farmer
from src.server.server import ChiaConnection
from src.types.protocols.plotter_protocol import PlotterHandshake, NewChallenge

logging.basicConfig(format='Farmer %(name)-12s: %(levelname)-8s %(message)s', level=logging.INFO)


async def timeout_loop(client_con: ChiaConnection):
    while True:
        await asyncio.sleep(5)
        await client_con.send("new_challenge", NewChallenge(secrets.token_bytes(32)))


async def main():
    client_con = ChiaConnection(farmer)
    client_server = await client_con.open_connection('127.0.0.1', 8000)

    await client_con.send("plotter_handshake", PlotterHandshake([sk.get_public_key() for sk in farmer.db.pool_sks]))
    timeout = asyncio.create_task(timeout_loop(client_con))
    await asyncio.gather(client_server, timeout)

asyncio.run(main())
