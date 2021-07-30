import asyncio

import aiohttp
import pytest

from chia.protocols.shared_protocol import protocol_version
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer, ssl_context_for_client
from chia.server.ws_connection import WSChiaConnection
from chia.ssl.create_ssl import generate_ca_signed_cert
from chia.types.peer_info import PeerInfo
from tests.block_tools import test_constants
from chia.util.ints import uint16
from tests.setup_nodes import (
    bt,
    self_hostname,
    setup_farmer_harvester,
    setup_introducer,
    setup_simulators_and_wallets,
    setup_timelord,
)


async def establish_connection(server: ChiaServer, dummy_port: int, ssl_context) -> bool:
    timeout = aiohttp.ClientTimeout(total=10)
    session = aiohttp.ClientSession(timeout=timeout)
    try:
        incoming_queue: asyncio.Queue = asyncio.Queue()
        url = f"wss://{self_hostname}:{server._port}/ws"
        ws = await session.ws_connect(url, autoclose=False, autoping=True, ssl=ssl_context)
        wsc = WSChiaConnection(
            NodeType.FULL_NODE,
            ws,
            server._port,
            server.log,
            True,
            False,
            self_hostname,
            incoming_queue,
            lambda x, y: x,
            None,
            100,
            30,
        )
        handshake = await wsc.perform_handshake(server._network_id, protocol_version, dummy_port, NodeType.FULL_NODE)
        await session.close()
        return handshake
    except Exception:
        await session.close()
        return False


class TestSSL:
    @pytest.fixture(scope="function")
    async def harvester_farmer(self):
        async for _ in setup_farmer_harvester(test_constants):
            yield _

    @pytest.fixture(scope="function")
    async def wallet_node(self):
        async for _ in setup_simulators_and_wallets(1, 1, {}):
            yield _

    @pytest.fixture(scope="function")
    async def introducer(self):
        async for _ in setup_introducer(21233):
            yield _

    @pytest.fixture(scope="function")
    async def timelord(self):
        async for _ in setup_timelord(21236, 21237, False, test_constants, bt):
            yield _

    @pytest.mark.asyncio
    async def test_public_connections(self, wallet_node):
        full_nodes, wallets = wallet_node
        full_node_api = full_nodes[0]
        server_1: ChiaServer = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]

        success = await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        assert success is True

    @pytest.mark.asyncio
    async def test_farmer(self, harvester_farmer):
        harvester_api, farmer_api = harvester_farmer

        farmer_server = farmer_api.farmer.server
        # Create valid cert (valid meaning signed with private CA)
        priv_crt = farmer_server._private_key_path.parent / "valid.crt"
        priv_key = farmer_server._private_key_path.parent / "valid.key"
        generate_ca_signed_cert(
            farmer_server.ca_private_crt_path.read_bytes(),
            farmer_server.ca_private_key_path.read_bytes(),
            priv_crt,
            priv_key,
        )
        ssl_context = ssl_context_for_client(
            farmer_server.ca_private_crt_path, farmer_server.ca_private_crt_path, priv_crt, priv_key
        )
        connected = await establish_connection(farmer_server, 12312, ssl_context)
        assert connected is True

        # Create not authenticated cert
        pub_crt = farmer_server._private_key_path.parent / "non_valid.crt"
        pub_key = farmer_server._private_key_path.parent / "non_valid.key"
        generate_ca_signed_cert(
            farmer_server.chia_ca_crt_path.read_bytes(), farmer_server.chia_ca_key_path.read_bytes(), pub_crt, pub_key
        )
        ssl_context = ssl_context_for_client(
            farmer_server.chia_ca_crt_path, farmer_server.chia_ca_crt_path, pub_crt, pub_key
        )
        connected = await establish_connection(farmer_server, 12312, ssl_context)
        assert connected is False
        ssl_context = ssl_context_for_client(
            farmer_server.ca_private_crt_path, farmer_server.ca_private_crt_path, pub_crt, pub_key
        )
        connected = await establish_connection(farmer_server, 12312, ssl_context)
        assert connected is False

    @pytest.mark.asyncio
    async def test_full_node(self, wallet_node):
        full_nodes, wallets = wallet_node
        full_node_api = full_nodes[0]
        full_node_server = full_node_api.full_node.server

        # Create not authenticated cert
        pub_crt = full_node_server._private_key_path.parent / "p2p.crt"
        pub_key = full_node_server._private_key_path.parent / "p2p.key"
        generate_ca_signed_cert(
            full_node_server.chia_ca_crt_path.read_bytes(),
            full_node_server.chia_ca_key_path.read_bytes(),
            pub_crt,
            pub_key,
        )
        ssl_context = ssl_context_for_client(
            full_node_server.chia_ca_crt_path, full_node_server.chia_ca_crt_path, pub_crt, pub_key
        )
        connected = await establish_connection(full_node_server, 12312, ssl_context)
        assert connected is True

    @pytest.mark.asyncio
    async def test_wallet(self, wallet_node):
        full_nodes, wallets = wallet_node
        wallet_node, wallet_server = wallets[0]

        # Wallet should not accept incoming connections
        pub_crt = wallet_server._private_key_path.parent / "p2p.crt"
        pub_key = wallet_server._private_key_path.parent / "p2p.key"
        generate_ca_signed_cert(
            wallet_server.chia_ca_crt_path.read_bytes(), wallet_server.chia_ca_key_path.read_bytes(), pub_crt, pub_key
        )
        ssl_context = ssl_context_for_client(
            wallet_server.chia_ca_crt_path, wallet_server.chia_ca_crt_path, pub_crt, pub_key
        )
        connected = await establish_connection(wallet_server, 12312, ssl_context)
        assert connected is False

        # Not even signed by private cert
        priv_crt = wallet_server._private_key_path.parent / "valid.crt"
        priv_key = wallet_server._private_key_path.parent / "valid.key"
        generate_ca_signed_cert(
            wallet_server.ca_private_crt_path.read_bytes(),
            wallet_server.ca_private_key_path.read_bytes(),
            priv_crt,
            priv_key,
        )
        ssl_context = ssl_context_for_client(
            wallet_server.ca_private_crt_path, wallet_server.ca_private_crt_path, priv_crt, priv_key
        )
        connected = await establish_connection(wallet_server, 12312, ssl_context)
        assert connected is False

    @pytest.mark.asyncio
    async def test_harvester(self, harvester_farmer):
        harvester, farmer_api = harvester_farmer
        harvester_server = harvester.server

        # harvester should not accept incoming connections
        pub_crt = harvester_server._private_key_path.parent / "p2p.crt"
        pub_key = harvester_server._private_key_path.parent / "p2p.key"
        generate_ca_signed_cert(
            harvester_server.chia_ca_crt_path.read_bytes(),
            harvester_server.chia_ca_key_path.read_bytes(),
            pub_crt,
            pub_key,
        )
        ssl_context = ssl_context_for_client(
            harvester_server.chia_ca_crt_path, harvester_server.chia_ca_crt_path, pub_crt, pub_key
        )
        connected = await establish_connection(harvester_server, 12312, ssl_context)
        assert connected is False

        # Not even signed by private cert
        priv_crt = harvester_server._private_key_path.parent / "valid.crt"
        priv_key = harvester_server._private_key_path.parent / "valid.key"
        generate_ca_signed_cert(
            harvester_server.ca_private_crt_path.read_bytes(),
            harvester_server.ca_private_key_path.read_bytes(),
            priv_crt,
            priv_key,
        )
        ssl_context = ssl_context_for_client(
            harvester_server.ca_private_crt_path, harvester_server.ca_private_crt_path, priv_crt, priv_key
        )
        connected = await establish_connection(harvester_server, 12312, ssl_context)
        assert connected is False

    @pytest.mark.asyncio
    async def test_introducer(self, introducer):
        introducer_api, introducer_server = introducer

        # Create not authenticated cert
        pub_crt = introducer_server.chia_ca_key_path.parent / "p2p.crt"
        pub_key = introducer_server.chia_ca_key_path.parent / "p2p.key"
        generate_ca_signed_cert(
            introducer_server.chia_ca_crt_path.read_bytes(),
            introducer_server.chia_ca_key_path.read_bytes(),
            pub_crt,
            pub_key,
        )
        ssl_context = ssl_context_for_client(
            introducer_server.chia_ca_crt_path, introducer_server.chia_ca_crt_path, pub_crt, pub_key
        )
        connected = await establish_connection(introducer_server, 12312, ssl_context)
        assert connected is True

    @pytest.mark.asyncio
    async def test_timelord(self, timelord):
        timelord_api, timelord_server = timelord

        # timelord should not accept incoming connections
        pub_crt = timelord_server._private_key_path.parent / "p2p.crt"
        pub_key = timelord_server._private_key_path.parent / "p2p.key"
        generate_ca_signed_cert(
            timelord_server.chia_ca_crt_path.read_bytes(),
            timelord_server.chia_ca_key_path.read_bytes(),
            pub_crt,
            pub_key,
        )
        ssl_context = ssl_context_for_client(
            timelord_server.chia_ca_crt_path, timelord_server.chia_ca_crt_path, pub_crt, pub_key
        )
        connected = await establish_connection(timelord_server, 12312, ssl_context)
        assert connected is False

        # Not even signed by private cert
        priv_crt = timelord_server._private_key_path.parent / "valid.crt"
        priv_key = timelord_server._private_key_path.parent / "valid.key"
        generate_ca_signed_cert(
            timelord_server.ca_private_crt_path.read_bytes(),
            timelord_server.ca_private_key_path.read_bytes(),
            priv_crt,
            priv_key,
        )
        ssl_context = ssl_context_for_client(
            timelord_server.ca_private_crt_path, timelord_server.ca_private_crt_path, priv_crt, priv_key
        )
        connected = await establish_connection(timelord_server, 12312, ssl_context)
        assert connected is False
