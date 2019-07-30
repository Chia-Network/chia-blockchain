import asyncio
import secrets
import logging
import random

from src import full_node
from src.server.server import ChiaConnection, start_server
from src.types.protocols.farmer_protocol import ProofOfSpaceFinalized

logging.basicConfig(format='Farmer %(name)-23s: %(levelname)-8s %(message)s', level=logging.INFO)


async def timeout_loop(client_con: ChiaConnection):
    height = 0
    while True:
        await asyncio.sleep(random.randint(1, 10))
        if random.random() < 0.7:
            height += 1
        await client_con.send("proof_of_space_finalized",
                              ProofOfSpaceFinalized(secrets.token_bytes(32),
                                                    height,
                                                    secrets.token_bytes(32)))


async def main():
    client_con = ChiaConnection(full_node)
    total_time: int = 0
    succeeded: bool = False
    while total_time < 20 and not succeeded:
        try:
            client_con = ChiaConnection(full_node, "farmer")
            await client_con.open_connection(full_node.farmer_ip, full_node.farmer_port)
            succeeded = True
        except ConnectionRefusedError:
            print(f"Connection to {full_node.farmer_ip}:{full_node.farmer_port} refused.")
            await asyncio.sleep(5)
        total_time += 5
    if not succeeded:
        raise TimeoutError("Failed to connect to plotter.")

    # Starts the full node server (which full nodes can connect to)
    server = asyncio.create_task(start_server(full_node, '127.0.0.1',
                                              full_node.full_node_port, "full_node"))

    # Starts a (hack) timeout to create challenges
    timeout = asyncio.create_task(timeout_loop(client_con))

    await asyncio.gather(timeout, server)

asyncio.run(main())
