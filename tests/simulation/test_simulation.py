import pytest
import pytest_asyncio

from chia.types.peer_info import PeerInfo
from tests.block_tools import create_block_tools_async
from chia.util.ints import uint16
from tests.core.node_height import node_height_at_least
from tests.setup_nodes import setup_full_node, setup_full_system, test_constants
from tests.time_out_assert import time_out_assert
from tests.util.keyring import TempKeyring
from tests.util.socket import find_available_listen_port

test_constants_modified = test_constants.replace(
    **{
        "DIFFICULTY_STARTING": 2 ** 8,
        "DISCRIMINANT_SIZE_BITS": 1024,
        "SUB_EPOCH_BLOCKS": 140,
        "WEIGHT_PROOF_THRESHOLD": 2,
        "WEIGHT_PROOF_RECENT_BLOCKS": 350,
        "MAX_SUB_SLOT_BLOCKS": 50,
        "NUM_SPS_SUB_SLOT": 32,  # Must be a power of 2
        "EPOCH_BLOCKS": 280,
        "SUB_SLOT_ITERS_STARTING": 2 ** 20,
        "NUMBER_ZERO_BITS_PLOT_FILTER": 5,
    }
)


# TODO: Ideally, the db_version should be the (parameterized) db_version
# fixture, to test all versions of the database schema. This doesn't work
# because of a hack in shutting down the full node, which means you cannot run
# more than one simulations per process.
@pytest_asyncio.fixture(scope="function")
async def extra_node(self_hostname):
    with TempKeyring() as keychain:
        b_tools = await create_block_tools_async(constants=test_constants_modified, keychain=keychain)
        async for _ in setup_full_node(
            test_constants_modified,
            "blockchain_test_3.db",
            self_hostname,
            find_available_listen_port(),
            find_available_listen_port(),
            b_tools,
            db_version=1,
        ):
            yield _


@pytest_asyncio.fixture(scope="function")
async def simulation(bt):
    async for _ in setup_full_system(test_constants_modified, bt, db_version=1):
        yield _


class TestSimulation:
    @pytest.mark.asyncio
    async def test_simulation_1(self, simulation, extra_node, self_hostname):
        node1, node2, _, _, _, _, _, _, _, sanitizer_server, server1 = simulation

        node1_port = node1.full_node.config["port"]
        node2_port = node2.full_node.config["port"]
        await server1.start_client(PeerInfo(self_hostname, uint16(node2_port)))
        # Use node2 to test node communication, since only node1 extends the chain.
        await time_out_assert(600, node_height_at_least, True, node2, 7)
        await sanitizer_server.start_client(PeerInfo(self_hostname, uint16(node2_port)))

        async def has_compact(node1, node2):
            peak_height_1 = node1.full_node.blockchain.get_peak_height()
            headers_1 = await node1.full_node.blockchain.get_header_blocks_in_range(0, peak_height_1 - 6)
            peak_height_2 = node2.full_node.blockchain.get_peak_height()
            headers_2 = await node2.full_node.blockchain.get_header_blocks_in_range(0, peak_height_2 - 6)
            # Commented to speed up.
            # cc_eos = [False, False]
            # icc_eos = [False, False]
            # cc_sp = [False, False]
            # cc_ip = [False, False]
            has_compact = [False, False]
            for index, headers in enumerate([headers_1, headers_2]):
                for header in headers.values():
                    for sub_slot in header.finished_sub_slots:
                        if sub_slot.proofs.challenge_chain_slot_proof.normalized_to_identity:
                            # cc_eos[index] = True
                            has_compact[index] = True
                        if (
                            sub_slot.proofs.infused_challenge_chain_slot_proof is not None
                            and sub_slot.proofs.infused_challenge_chain_slot_proof.normalized_to_identity
                        ):
                            # icc_eos[index] = True
                            has_compact[index] = True
                    if (
                        header.challenge_chain_sp_proof is not None
                        and header.challenge_chain_sp_proof.normalized_to_identity
                    ):
                        # cc_sp[index] = True
                        has_compact[index] = True
                    if header.challenge_chain_ip_proof.normalized_to_identity:
                        # cc_ip[index] = True
                        has_compact[index] = True

            # return (
            #     cc_eos == [True, True] and icc_eos == [True, True] and cc_sp == [True, True] and cc_ip == [True, True]
            # )
            return has_compact == [True, True]

        await time_out_assert(600, has_compact, True, node1, node2)
        node3 = extra_node
        server3 = node3.full_node.server
        peak_height = max(node1.full_node.blockchain.get_peak_height(), node2.full_node.blockchain.get_peak_height())
        await server3.start_client(PeerInfo(self_hostname, uint16(node1_port)))
        await server3.start_client(PeerInfo(self_hostname, uint16(node2_port)))
        await time_out_assert(600, node_height_at_least, True, node3, peak_height)
