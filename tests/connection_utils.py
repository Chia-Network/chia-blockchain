import asyncio
import logging
from typing import Tuple

import aiohttp
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization

from chia.protocols.shared_protocol import protocol_version
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer, ssl_context_for_client
from chia.server.ws_connection import WSChiaConnection
from chia.ssl.create_ssl import generate_ca_signed_cert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16
from tests.setup_nodes import self_hostname
from tests.time_out_assert import time_out_assert

log = logging.getLogger(__name__)


async def disconnect_all_and_reconnect(server: ChiaServer, reconnect_to: ChiaServer) -> bool:
    cons = list(server.all_connections.values())[:]
    for con in cons:
        await con.close()
    return await server.start_client(PeerInfo(self_hostname, uint16(reconnect_to._port)), None)


async def add_dummy_connection(server: ChiaServer, dummy_port: int) -> Tuple[asyncio.Queue, bytes32]:
    timeout = aiohttp.ClientTimeout(total=10)
    session = aiohttp.ClientSession(timeout=timeout)
    incoming_queue: asyncio.Queue = asyncio.Queue()
    dummy_crt_path = server._private_key_path.parent / "dummy.crt"
    dummy_key_path = server._private_key_path.parent / "dummy.key"
    generate_ca_signed_cert(
        server.chia_ca_crt_path.read_bytes(), server.chia_ca_key_path.read_bytes(), dummy_crt_path, dummy_key_path
    )
    ssl_context = ssl_context_for_client(
        server.chia_ca_crt_path, server.chia_ca_key_path, dummy_crt_path, dummy_key_path
    )
    pem_cert = x509.load_pem_x509_certificate(dummy_crt_path.read_bytes(), default_backend())
    der_cert = x509.load_der_x509_certificate(pem_cert.public_bytes(serialization.Encoding.DER), default_backend())
    peer_id = bytes32(der_cert.fingerprint(hashes.SHA256()))
    url = f"wss://{self_hostname}:{server._port}/ws"
    ws = await session.ws_connect(url, autoclose=True, autoping=True, ssl=ssl_context)
    wsc = WSChiaConnection(
        NodeType.FULL_NODE,
        ws,
        server._port,
        log,
        True,
        False,
        self_hostname,
        incoming_queue,
        lambda x, y: x,
        peer_id,
        100,
        30,
    )
    handshake = await wsc.perform_handshake(server._network_id, protocol_version, dummy_port, NodeType.FULL_NODE)
    assert handshake is True
    return incoming_queue, peer_id


async def connect_and_get_peer(server_1: ChiaServer, server_2: ChiaServer) -> WSChiaConnection:
    """
    Connect server_2 to server_1, and get return the connection in server_1.
    """
    await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)))

    async def connected():
        for node_id_c, _ in server_1.all_connections.items():
            if node_id_c == server_2.node_id:
                return True
        return False

    await time_out_assert(10, connected, True)
    for node_id, wsc in server_1.all_connections.items():
        if node_id == server_2.node_id:
            return wsc
    assert False
