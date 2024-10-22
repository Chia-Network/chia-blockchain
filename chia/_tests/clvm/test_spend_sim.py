from __future__ import annotations

import pytest
from chia_rs import G2Element

from chia.clvm.spend_sim import sim_and_client
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import compute_additions, make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle


@pytest.mark.anyio
async def test_farming():
    async with sim_and_client(pass_prefarm=False) as (sim, _):
        for i in range(0, 5):
            await sim.farm_block()

        assert len(sim.blocks) == 5
        assert sim.blocks[-1].height == 4
        assert sim.block_records[0].reward_claims_incorporated[0].amount == 18375000000000000000


@pytest.mark.anyio
async def test_rewind():
    async with sim_and_client() as (sim, _):
        for i in range(0, 5):
            await sim.farm_block()

        save_height = sim.get_height()
        await sim.farm_block()
        await sim.rewind(save_height)

        assert len(sim.blocks) == 6
        assert sim.blocks[-1].height == 5


@pytest.mark.anyio
async def test_all_endpoints():
    async with sim_and_client() as (sim, sim_client):
        for i in range(0, 5):
            await sim.farm_block()
        await sim.farm_block(bytes32([0] * 32))
        await sim.farm_block(bytes32([1] * 32))
        for i in range(0, 5):
            await sim.farm_block()

        # get_coin_records_by_hint
        acs = Program.to(1)
        acs_ph = acs.get_tree_hash()
        await sim.farm_block(acs_ph)
        coin_records = await sim_client.get_coin_records_by_puzzle_hash(acs.get_tree_hash())
        coin = coin_records[0].coin
        hint = Program.to("hint").get_tree_hash()
        non_existent_hint = Program.to("non_existent_hint").get_tree_hash()
        acs_hint_spent = make_spend(
            coin,
            acs,
            Program.to([[ConditionOpcode.CREATE_COIN, acs.get_tree_hash(), 2, [hint]]]),
        )
        hinted_coin = compute_additions(acs_hint_spent)[0]
        acs_hint_unspent = make_spend(
            hinted_coin,
            acs,
            Program.to([[ConditionOpcode.CREATE_COIN, acs.get_tree_hash(), 1, [hint]]]),
        )
        await sim_client.push_tx(SpendBundle([acs_hint_spent, acs_hint_unspent], G2Element()))
        await sim.farm_block(acs_ph)
        coin_records = await sim_client.get_coin_records_by_hint(hint, include_spent_coins=False)
        assert len(coin_records) == 1
        coin_records = await sim_client.get_coin_records_by_hint(hint, include_spent_coins=True)
        assert len(coin_records) == 2
        coin_records = await sim_client.get_coin_records_by_hint(non_existent_hint)
        assert len(coin_records) == 0
        coin_records = await sim_client.get_coin_records_by_puzzle_hash(acs.get_tree_hash())
        next_coin = coin_records[-1].coin
        height = sim.get_height()
        acs_hint_next_coin = make_spend(
            next_coin,
            acs,
            Program.to([[ConditionOpcode.CREATE_COIN, acs.get_tree_hash(), 2, [hint]]]),
        )
        await sim_client.push_tx(SpendBundle([acs_hint_next_coin], G2Element()))
        await sim.farm_block(acs_ph)
        coin_records = await sim_client.get_coin_records_by_hint(hint, start_height=height + 1, end_height=height + 2)
        assert len(coin_records) == 1
        coin_records = await sim_client.get_coin_records_by_hint(hint, start_height=height)
        assert len(coin_records) == 3
        coin_records = await sim_client.get_coin_records_by_hint(hint, end_height=height + 1)
        assert len(coin_records) == 2
        coin_records = await sim_client.get_coin_records_by_hint(hint, end_height=height + 1, include_spent_coins=False)
        assert len(coin_records) == 1
        coin_records = await sim_client.get_coin_records_by_hint(hint, start_height=height + 3)
        assert len(coin_records) == 0

        # get_coin_records_by_puzzle_hash
        coin_records = await sim_client.get_coin_records_by_puzzle_hash(bytes32([0] * 32))
        coin_record_name = coin_records[0].coin.name()
        assert len(coin_records) == 2

        coin_records = await sim_client.get_coin_records_by_puzzle_hash(bytes32([0] * 32), start_height=0, end_height=2)
        assert len(coin_records) == 0

        # get_coin_records_by_puzzle_hashes
        coin_records = await sim_client.get_coin_records_by_puzzle_hashes([bytes32([0] * 32), bytes32([1] * 32)])
        assert len(coin_records) == 4

        coin_records = await sim_client.get_coin_records_by_puzzle_hashes(
            [bytes32([0] * 32), bytes32([1] * 32)], start_height=0, end_height=2
        )
        assert len(coin_records) == 0

        # get_coin_record_by_name
        assert await sim_client.get_coin_record_by_name(coin_record_name)

        # get_block_records
        block_records = await sim_client.get_block_records(0, 5)
        assert len(block_records) == 5

        # get_block_record_by_height
        block_record = await sim_client.get_block_record_by_height(0)
        assert block_record
        assert block_record == block_records[0]

        # get_block_record
        same_block_record = await sim_client.get_block_record(block_record.header_hash)
        assert same_block_record == block_record

        # get_block
        full_block = await sim_client.get_block(block_record.header_hash)
        assert full_block.transactions_generator is None

        # get_all_block
        full_blocks = await sim_client.get_all_block(0, 5)
        assert full_blocks[0] == full_block

        # push_tx
        puzzle_hash = bytes.fromhex("9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2")  # Program.to(1)
        await sim.farm_block(puzzle_hash)
        spendable_coin = await sim_client.get_coin_records_by_puzzle_hash(puzzle_hash, include_spent_coins=False)
        spendable_coin = spendable_coin[0].coin
        bundle = SpendBundle(
            [
                make_spend(
                    spendable_coin,
                    Program.to(1),
                    Program.to([[51, puzzle_hash, 1]]),
                )
            ],
            G2Element(),
        )
        result, error = await sim_client.push_tx(bundle)
        assert not error
        # get_all_mempool_tx_ids
        mempool_items = await sim_client.get_all_mempool_tx_ids()
        assert len(mempool_items) == 1

        # get_mempool_item_by_tx_id
        mempool_item = await sim_client.get_mempool_item_by_tx_id(mempool_items[0])
        assert mempool_item

        # get_all_mempool_items
        mempool_items = await sim_client.get_all_mempool_items()
        assert len(mempool_items) == 1

        # get_additions_and_removals
        await sim.farm_block()
        latest_block = sim.block_records[-1]
        additions, removals = await sim_client.get_additions_and_removals(latest_block.header_hash)
        assert additions
        assert removals

        # get_puzzle_and_solution
        coin_spend = await sim_client.get_puzzle_and_solution(spendable_coin.name(), latest_block.height)
        assert coin_spend == bundle.coin_spends[0]

        # get_coin_records_by_parent_ids
        new_coin = next(x.coin for x in additions if x.coin.puzzle_hash == puzzle_hash)
        coin_records = await sim_client.get_coin_records_by_parent_ids([spendable_coin.name()])
        assert coin_records[0].coin.name() == new_coin.name()
