from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from chia._tests.cmds.cmd_test_utils import TestFullNodeRpcClient, TestRpcClients, run_cli_command_and_assert
from chia._tests.cmds.testing_classes import hash_to_height, height_hash
from chia._tests.util.test_full_block_utils import get_foliage, get_reward_chain_block, get_transactions_info, vdf_proof
from chia.types.blockchain_format.foliage import FoliageTransactionBlock
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.full_block import FullBlock
from chia.util.ints import uint32, uint64


@dataclass
class ShowFullNodeRpcClient(TestFullNodeRpcClient):
    async def get_fee_estimate(self, target_times: Optional[List[int]], cost: Optional[int]) -> Dict[str, Any]:
        self.add_to_log("get_fee_estimate", (target_times, cost))
        response: Dict[str, Any] = {
            "current_fee_rate": 0,
            "estimates": [0, 0, 0],
            "fee_rate_last_block": 30769.681426718744,
            "fees_last_block": 500000000000,
            "full_node_synced": True,
            "last_block_cost": 16249762,
            "last_peak_timestamp": 1688858763,
            "last_tx_block_height": 11,
            "mempool_fees": 0,
            "mempool_max_size": 0,
            "mempool_size": 0,
            "node_time_utc": 1689187617,
            "num_spends": 0,
            "peak_height": 11,
            "success": True,
            "target_times": target_times,
        }
        return response

    async def get_block(self, header_hash: bytes32) -> Optional[FullBlock]:
        # we return a block with the height matching the header hash
        self.add_to_log("get_block", (header_hash,))
        height = hash_to_height(header_hash)
        foliage = None
        for foliage in get_foliage():
            break
        assert foliage is not None
        r_chain_block = None
        for r_chain_block in get_reward_chain_block(height=uint32(height)):
            break
        assert r_chain_block is not None
        foliage_tx_block = FoliageTransactionBlock(
            prev_transaction_block_hash=height_hash(height - 1),
            timestamp=uint64(100400000),
            filter_hash=bytes32([2] * 32),
            additions_root=bytes32([3] * 32),
            removals_root=bytes32([4] * 32),
            transactions_info_hash=bytes32([5] * 32),
        )
        tx_info = None
        for tx_info in get_transactions_info(height=uint32(height), foliage_transaction_block=foliage_tx_block):
            break
        assert tx_info is not None
        full_block = FullBlock(
            finished_sub_slots=[],
            reward_chain_block=r_chain_block,
            challenge_chain_sp_proof=None,
            challenge_chain_ip_proof=vdf_proof(),
            reward_chain_sp_proof=None,
            reward_chain_ip_proof=vdf_proof(),
            infused_challenge_chain_ip_proof=None,
            foliage=foliage,
            foliage_transaction_block=foliage_tx_block,
            transactions_info=tx_info,
            transactions_generator=SerializedProgram.from_bytes(bytes.fromhex("ff01820539")),
            transactions_generator_ref_list=[],
        )
        return full_block


RPC_CLIENT_TO_USE = ShowFullNodeRpcClient()  # pylint: disable=no-value-for-parameter


def test_chia_show(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients
    # set RPC Client
    test_rpc_clients.full_node_rpc_client = RPC_CLIENT_TO_USE
    # get output with all options
    command_args = [
        "show",
        "-s",
        "-f",
        "--block-header-hash-by-height",
        "10",
        "-b0x000000000000000000000000000000000000000000000000000000000000000b",
    ]
    # these are various things that should be in the output
    assert_list = [
        "Current Blockchain Status: Full Node Synced",
        "Estimated network space: 25.647 EiB",
        "Block fees: 500000000000 mojos",
        "Fee rate:    3.077e+04 mojos per CLVM cost",
        f"Tx Filter Hash         {bytes32([2] * 32).hex()}",
        "Weight                 10000",
        "Is a Transaction Block?True",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: dict[str, Optional[List[tuple[Any, ...]]]] = {  # name of rpc: (args)
        "get_blockchain_state": None,
        "get_block_record": [(height_hash(height),) for height in [11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 11, 10]],
        "get_block_record_by_height": [(10,)],
        "get_fee_estimate": [([60, 120, 300], 1)],
        "get_block": [(height_hash(11),)],
    }  # these RPC's should be called with these variables.
    test_rpc_clients.full_node_rpc_client.check_log(expected_calls)
