import asyncio

import aiohttp
import pytest

from chia.protocols.shared_protocol import protocol_version, capabilities
from chia.server.outbound_message import NodeType
from chia.server.server import ChiaServer, ssl_context_for_client
from chia.server.ws_connection import WSChiaConnection
from chia.ssl.create_ssl import generate_ca_signed_cert
from chia.types.peer_info import PeerInfo
from chia.util.ints import uint16


async def establish_connection(server: ChiaServer, self_hostname: str, ssl_context) -> None:
    timeout = aiohttp.ClientTimeout(total=10)
    dummy_port = 5  # this does not matter
    async with aiohttp.ClientSession(timeout=timeout) as session:
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
            local_capabilities_for_handshake=capabilities,
        )
        await wsc.perform_handshake(server._network_id, protocol_version, dummy_port, NodeType.FULL_NODE)


class TestSSL:
    @pytest.mark.asyncio
    async def test_public_connections(self, wallet_node_sim_and_wallet, self_hostname):
        full_nodes, wallets, _ = wallet_node_sim_and_wallet
        full_node_api = full_nodes[0]
        server_1: ChiaServer = full_node_api.full_node.server
        wallet_node, server_2 = wallets[0]

        success = await server_2.start_client(PeerInfo(self_hostname, uint16(server_1._port)), None)
        assert success is True

    @pytest.mark.asyncio
    async def test_farmer(self, farmer_one_harvester, self_hostname):
        _, farmer_service, _ = farmer_one_harvester
        farmer_api = farmer_service._api

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
            farmer_server.ca_private_crt_path, farmer_server.ca_private_key_path, priv_crt, priv_key
        )
        await establish_connection(farmer_server, self_hostname, ssl_context)

        # Create not authenticated cert
        pub_crt = farmer_server._private_key_path.parent / "non_valid.crt"
        pub_key = farmer_server._private_key_path.parent / "non_valid.key"
        generate_ca_signed_cert(
            farmer_server.chia_ca_crt_path.read_bytes(), farmer_server.chia_ca_key_path.read_bytes(), pub_crt, pub_key
        )
        ssl_context = ssl_context_for_client(
            farmer_server.chia_ca_crt_path, farmer_server.chia_ca_key_path, pub_crt, pub_key
        )
        with pytest.raises(aiohttp.ClientConnectorCertificateError):
            await establish_connection(farmer_server, self_hostname, ssl_context)
        ssl_context = ssl_context_for_client(
            farmer_server.ca_private_crt_path, farmer_server.ca_private_key_path, pub_crt, pub_key
        )
        with pytest.raises(aiohttp.ServerDisconnectedError):
            await establish_connection(farmer_server, self_hostname, ssl_context)

    @pytest.mark.asyncio
    async def test_full_node(self, wallet_node_sim_and_wallet, self_hostname):
        full_nodes, wallets, _ = wallet_node_sim_and_wallet
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
            full_node_server.chia_ca_crt_path, full_node_server.chia_ca_key_path, pub_crt, pub_key
        )
        await establish_connection(full_node_server, self_hostname, ssl_context)

    @pytest.mark.asyncio
    async def test_wallet(self, wallet_node_sim_and_wallet, self_hostname):
        full_nodes, wallets, _ = wallet_node_sim_and_wallet
        wallet_node, wallet_server = wallets[0]

        # Wallet should not accept incoming connections
        pub_crt = wallet_server._private_key_path.parent / "p2p.crt"
        pub_key = wallet_server._private_key_path.parent / "p2p.key"
        generate_ca_signed_cert(
            wallet_server.chia_ca_crt_path.read_bytes(), wallet_server.chia_ca_key_path.read_bytes(), pub_crt, pub_key
        )
        ssl_context = ssl_context_for_client(
            wallet_server.chia_ca_crt_path, wallet_server.chia_ca_key_path, pub_crt, pub_key
        )
        with pytest.raises(aiohttp.ClientConnectorError):
            await establish_connection(wallet_server, self_hostname, ssl_context)

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
            wallet_server.ca_private_crt_path, wallet_server.ca_private_key_path, priv_crt, priv_key
        )
        with pytest.raises(aiohttp.ClientConnectorError):
            await establish_connection(wallet_server, self_hostname, ssl_context)

    @pytest.mark.asyncio
    async def test_harvester(self, farmer_one_harvester, self_hostname):
        harvesters, _, _ = farmer_one_harvester
        harvester_server = harvesters[0]._server

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
            harvester_server.chia_ca_crt_path, harvester_server.chia_ca_key_path, pub_crt, pub_key
        )
        with pytest.raises(aiohttp.ClientConnectorError):
            await establish_connection(harvester_server, self_hostname, ssl_context)

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
            harvester_server.ca_private_crt_path, harvester_server.ca_private_key_path, priv_crt, priv_key
        )
        with pytest.raises(aiohttp.ClientConnectorError):
            await establish_connection(harvester_server, self_hostname, ssl_context)

    @pytest.mark.asyncio
    async def test_introducer(self, introducer, self_hostname):
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
            introducer_server.chia_ca_crt_path, introducer_server.chia_ca_key_path, pub_crt, pub_key
        )
        await establish_connection(introducer_server, self_hostname, ssl_context)

    @pytest.mark.asyncio
    async def test_timelord(self, timelord, self_hostname):
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
            timelord_server.chia_ca_crt_path, timelord_server.chia_ca_key_path, pub_crt, pub_key
        )
        with pytest.raises(aiohttp.ClientConnectorError):
            await establish_connection(timelord_server, self_hostname, ssl_context)

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
            timelord_server.ca_private_crt_path, timelord_server.ca_private_key_path, priv_crt, priv_key
        )
        with pytest.raises(aiohttp.ClientConnectorError):
            await establish_connection(timelord_server, self_hostname, ssl_context)
