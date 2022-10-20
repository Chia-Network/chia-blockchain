from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Tuple

import pytest
import pytest_asyncio

from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.simulator.simulator_full_node_rpc_client import SimulatorFullNodeRpcClient
from chia.simulator.simulator_test_tools import get_full_chia_simulator, get_puzzle_hash_from_key
from chia.simulator.time_out_assert import time_out_assert
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.hash import std_hash
from chia.util.ints import uint16
from chia.util.keychain import Keychain


async def get_num_coins_for_ph(simulator_client: SimulatorFullNodeRpcClient, ph: bytes32) -> int:
    return len(await simulator_client.get_coin_records_by_puzzle_hash(ph))


class TestStartSimulator:
    """
    These tests are designed to test the user facing functionality of the simulator.
    """

    @pytest_asyncio.fixture(scope="function")
    async def get_chia_simulator(
        self, tmp_path: Path, empty_keyring: Keychain
    ) -> AsyncGenerator[Tuple[FullNodeSimulator, Path, Dict[str, Any], str, int, Keychain], None]:
        async for simulator_args in get_full_chia_simulator(chia_root=tmp_path, keychain=empty_keyring):
            yield simulator_args

    @pytest.mark.asyncio
    async def test_start_simulator(
        self, get_chia_simulator: Tuple[FullNodeSimulator, Path, Dict[str, Any], str, int, Keychain]
    ) -> None:
        simulator, root_path, config, mnemonic, fingerprint, keychain = get_chia_simulator
        ph_1: bytes32 = get_puzzle_hash_from_key(keychain=keychain, fingerprint=fingerprint, key_id=1)
        ph_2: bytes32 = get_puzzle_hash_from_key(keychain=keychain, fingerprint=fingerprint, key_id=2)
        dummy_hash: bytes32 = std_hash(b"test")
        num_blocks = 2
        # connect to rpc
        rpc_port = config["full_node"]["rpc_port"]
        simulator_rpc_client = await SimulatorFullNodeRpcClient.create(
            config["self_hostname"], uint16(rpc_port), root_path, config
        )
        # test auto_farm logic
        assert await simulator_rpc_client.get_auto_farming()
        await time_out_assert(10, simulator_rpc_client.set_auto_farming, False, False)
        await simulator.autofarm_transaction(dummy_hash)  # this should do nothing
        await asyncio.sleep(3)  # wait for block to be processed
        assert len(await simulator.get_all_full_blocks()) == 0

        # now check if auto_farm is working
        await time_out_assert(10, simulator_rpc_client.set_auto_farming, True, True)
        for i in range(num_blocks):
            await simulator.autofarm_transaction(dummy_hash)
        await time_out_assert(10, simulator.full_node.blockchain.get_peak_height, 2)
        # check if reward was sent to correct target
        await time_out_assert(10, get_num_coins_for_ph, 2, simulator_rpc_client, ph_1)
        # test both block RPC's
        await simulator_rpc_client.farm_block(ph_2)
        new_height = await simulator_rpc_client.farm_block(ph_2, guarantee_tx_block=True)
        # check if farming reward was received correctly & if block was created
        await time_out_assert(10, simulator.full_node.blockchain.get_peak_height, new_height)
        await time_out_assert(10, get_num_coins_for_ph, 2, simulator_rpc_client, ph_2)
        # test balance rpc
        ph_amount = await simulator_rpc_client.get_all_puzzle_hashes()
        assert ph_amount[ph_2][0] == 2000000000000
        assert ph_amount[ph_2][1] == 2
        # test all coins rpc.
        coin_records = await simulator_rpc_client.get_all_coins()
        ph_2_total = 0
        ph_1_total = 0
        for cr in coin_records:
            if cr.coin.puzzle_hash == ph_2:
                ph_2_total += cr.coin.amount
            elif cr.coin.puzzle_hash == ph_1:
                ph_1_total += cr.coin.amount
        assert ph_2_total == 2000000000000 and ph_1_total == 4000000000000

        # block rpc tests.
        # test reorg
        old_blocks = await simulator_rpc_client.get_all_blocks()
        assert len(old_blocks) == 5

        # Sometimes in CI reorg_blocks takes a long time and the RPC times out
        # We can ignore this timeout as long as the subsequent tests pass
        try:
            await simulator_rpc_client.reorg_blocks(2)  # fork point 2 blocks, now height is 5
        except asyncio.exceptions.TimeoutError:
            pass  # ignore this error and hope the reorg is going ahead

        # wait up to 5 mins
        await time_out_assert(300, simulator.full_node.blockchain.get_peak_height, 5)
        # now validate that the blocks don't match
        assert (await simulator.get_all_full_blocks())[0:4] != old_blocks
        # test block deletion
        await simulator_rpc_client.revert_blocks(3)  # height 5 to 2
        await time_out_assert(10, simulator.full_node.blockchain.get_peak_height, 2)
        await time_out_assert(10, get_num_coins_for_ph, 2, simulator_rpc_client, ph_1)
        # close up
        simulator_rpc_client.close()
        await simulator_rpc_client.await_closed()
