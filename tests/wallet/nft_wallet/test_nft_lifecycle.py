from __future__ import annotations

import itertools
from typing import List

import pytest
from blspy import G2Element

from chia.clvm.spend_sim import CostLogger, sim_and_client
from chia.types.announcement import Announcement
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.wallet.nft_wallet.nft_puzzles import (
    NFT_METADATA_UPDATER,
    NFT_TRANSFER_PROGRAM_DEFAULT,
    construct_ownership_layer,
    create_nft_layer_puzzle_with_curry_params,
    metadata_to_program,
)

ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()


@pytest.mark.asyncio()
@pytest.mark.parametrize("metadata_updater", ["default"])
async def test_state_layer(cost_logger: CostLogger, metadata_updater: str) -> None:
    async with sim_and_client() as (sim, sim_client):
        if metadata_updater == "default":
            METADATA: Program = metadata_to_program(
                {
                    b"u": ["hey hey"],
                    b"lu": ["You have no permissions grr"],
                    b"mu": ["This but off chain"],
                    b"foo": ["Can't update this"],
                }
            )
            METADATA_UPDATER: Program = NFT_METADATA_UPDATER
        else:
            # TODO: Add test for updateable
            return
        METADATA_UPDATER_PUZZLE_HASH: bytes32 = METADATA_UPDATER.get_tree_hash()

        state_layer_puzzle: Program = create_nft_layer_puzzle_with_curry_params(
            METADATA, METADATA_UPDATER_PUZZLE_HASH, ACS
        )
        state_layer_ph: bytes32 = state_layer_puzzle.get_tree_hash()
        await sim.farm_block(state_layer_ph)
        state_layer_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(state_layer_ph, include_spent_coins=False)
        )[0].coin

        generic_spend = CoinSpend(
            state_layer_coin,
            state_layer_puzzle,
            Program.to([[[51, ACS_PH, 1]]]),
        )
        generic_bundle = cost_logger.add_cost(
            "State layer only coin - one child created", SpendBundle([generic_spend], G2Element())
        )

        result = await sim_client.push_tx(generic_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()

        if metadata_updater == "default":
            metadata_updater_solutions: List[Program] = [
                Program.to((b"u", "update")),
                Program.to((b"lu", "update")),
                Program.to((b"mu", "update")),
                Program.to((b"foo", "update")),
            ]
            expected_metadatas: List[Program] = [
                metadata_to_program(
                    {
                        b"u": ["update", "hey hey"],
                        b"lu": ["You have no permissions grr"],
                        b"mu": ["This but off chain"],
                        b"foo": ["Can't update this"],
                    }
                ),
                metadata_to_program(
                    {
                        b"u": ["update", "hey hey"],
                        b"lu": ["update", "You have no permissions grr"],
                        b"mu": ["This but off chain"],
                        b"foo": ["Can't update this"],
                    }
                ),
                metadata_to_program(
                    {
                        b"u": ["update", "hey hey"],
                        b"lu": ["update", "You have no permissions grr"],
                        b"mu": ["update", "This but off chain"],
                        b"foo": ["Can't update this"],
                    }
                ),
                metadata_to_program(
                    {  # no change
                        b"u": ["update", "hey hey"],
                        b"lu": ["update", "You have no permissions grr"],
                        b"mu": ["update", "This but off chain"],
                        b"foo": ["Can't update this"],
                    }
                ),
            ]
        else:
            return

        for solution, metadata in zip(metadata_updater_solutions, expected_metadatas):
            state_layer_coin = (
                await sim_client.get_coin_records_by_parent_ids([state_layer_coin.name()], include_spent_coins=False)
            )[0].coin
            update_spend = CoinSpend(
                state_layer_coin,
                state_layer_puzzle,
                Program.to(
                    [
                        [
                            [51, ACS_PH, 1],
                            [-24, METADATA_UPDATER, solution],
                        ]
                    ]
                ),
            )
            update_bundle = cost_logger.add_cost(
                "State layer only coin (metadata update) - one child created", SpendBundle([update_spend], G2Element())
            )
            result = await sim_client.push_tx(update_bundle)
            assert result == (MempoolInclusionStatus.SUCCESS, None)
            await sim.farm_block()
            state_layer_puzzle = create_nft_layer_puzzle_with_curry_params(metadata, METADATA_UPDATER_PUZZLE_HASH, ACS)


@pytest.mark.asyncio()
async def test_ownership_layer(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, sim_client):
        TARGET_OWNER = bytes32([0] * 32)
        TARGET_TP = Program.to([8])  # (x)
        # (a (i 11 (q 4 19 (c 43 (q ()))) (q 8)) 1) or
        # (mod (_ _ solution) (if solution (list (f solution) (f (r solution)) ()) (x)))
        transfer_program = Program.to([2, [3, 11, [1, 4, 19, [4, 43, [1, []]]], [1, 8]], 1])

        ownership_puzzle: Program = construct_ownership_layer(
            None,
            transfer_program,
            ACS,
        )
        ownership_ph: bytes32 = ownership_puzzle.get_tree_hash()
        await sim.farm_block(ownership_ph)
        ownership_coin = (await sim_client.get_coin_records_by_puzzle_hash(ownership_ph, include_spent_coins=False))[
            0
        ].coin

        generic_spend = CoinSpend(
            ownership_coin,
            ownership_puzzle,
            Program.to([[[51, ACS_PH, 1], [-10, [], []]]]),
        )
        generic_bundle = cost_logger.add_cost(
            "Ownership only coin - one child created", SpendBundle([generic_spend], G2Element())
        )
        result = await sim_client.push_tx(generic_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        ownership_coin = (await sim_client.get_coin_records_by_puzzle_hash(ownership_ph, include_spent_coins=False))[
            0
        ].coin

        skip_tp_spend = CoinSpend(
            ownership_coin,
            ownership_puzzle,
            Program.to([[[51, ACS_PH, 1]]]),
        )
        skip_tp_bundle = SpendBundle([skip_tp_spend], G2Element())

        result = await sim_client.push_tx(skip_tp_bundle)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)
        with pytest.raises(ValueError, match="clvm raise"):
            skip_tp_spend.puzzle_reveal.to_program().run(skip_tp_spend.solution.to_program())

        make_bad_announcement_spend = CoinSpend(
            ownership_coin,
            ownership_puzzle,
            Program.to(
                [
                    [
                        [51, ACS_PH, 1],
                        [-10, TARGET_OWNER, TARGET_TP],
                        [62, b"\xad\x4c" + bytes32([0] * 32)],
                    ]
                ]
            ),
        )
        make_bad_announcement_bundle = SpendBundle([make_bad_announcement_spend], G2Element())

        result = await sim_client.push_tx(make_bad_announcement_bundle)
        assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)
        with pytest.raises(ValueError, match="clvm raise"):
            make_bad_announcement_spend.puzzle_reveal.to_program().run(
                make_bad_announcement_spend.solution.to_program()
            )

        expected_announcement = Announcement(
            ownership_puzzle.get_tree_hash(),
            b"\xad\x4c" + Program.to([TARGET_OWNER, TARGET_TP]).get_tree_hash(),
        )
        harmless_announcement = Announcement(
            ownership_puzzle.get_tree_hash(),
            b"oy",
        )
        update_everything_spend = CoinSpend(
            ownership_coin,
            ownership_puzzle,
            Program.to(
                [
                    [
                        [51, ACS_PH, 1],
                        [-10, TARGET_OWNER, TARGET_TP],
                        [62, harmless_announcement.message],  # create a harmless puzzle announcement
                        [63, expected_announcement.name()],
                        [63, harmless_announcement.name()],
                    ]
                ]
            ),
        )
        update_everything_bundle = cost_logger.add_cost(
            "Ownership only coin (update owner and TP) - one child + 3 announcements created",
            SpendBundle([update_everything_spend], G2Element()),
        )
        result = await sim_client.push_tx(update_everything_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        assert (await sim_client.get_coin_records_by_parent_ids([ownership_coin.name()], include_spent_coins=False))[
            0
        ].coin.puzzle_hash == construct_ownership_layer(
            TARGET_OWNER,
            TARGET_TP,
            ACS,
        ).get_tree_hash()


@pytest.mark.asyncio()
async def test_default_transfer_program(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, sim_client):
        # Now make the ownership coin
        FAKE_SINGLETON_MOD = Program.to([2, 5, 11])  # (a 5 11) | (mod (_ INNER_PUZ inner_sol) (a INNER_PUZ inner_sol))
        FAKE_CAT_MOD = Program.to([2, 11, 23])  # (a 11 23) or (mod (_ _ INNER_PUZ inner_sol) (a INNER_PUZ inner_sol))
        FAKE_LAUNCHER_ID = bytes32([0] * 32)
        FAKE_TAIL = bytes32([2] * 32)
        FAKE_SINGLETON_STRUCT = Program.to((FAKE_SINGLETON_MOD.get_tree_hash(), (FAKE_LAUNCHER_ID, FAKE_LAUNCHER_ID)))
        FAKE_SINGLETON = FAKE_SINGLETON_MOD.curry(FAKE_SINGLETON_STRUCT, ACS)
        FAKE_CAT = FAKE_CAT_MOD.curry(FAKE_CAT_MOD.get_tree_hash(), FAKE_TAIL, ACS)

        ROYALTY_ADDRESS = bytes32([1] * 32)
        TRADE_PRICE_PERCENTAGE = 5000  # 50%
        transfer_program: Program = NFT_TRANSFER_PROGRAM_DEFAULT.curry(
            FAKE_SINGLETON_STRUCT,
            ROYALTY_ADDRESS,
            TRADE_PRICE_PERCENTAGE,
        )
        ownership_puzzle: Program = construct_ownership_layer(
            None,
            transfer_program,
            ACS,
        )
        ownership_ph: bytes32 = ownership_puzzle.get_tree_hash()
        await sim.farm_block(ownership_ph)
        ownership_coin = (await sim_client.get_coin_records_by_puzzle_hash(ownership_ph, include_spent_coins=False))[
            0
        ].coin

        BLOCK_HEIGHT = sim.block_height

        # Try a spend, no royalties, no owner update
        generic_spend = CoinSpend(
            ownership_coin,
            ownership_puzzle,
            Program.to([[[51, ACS_PH, 1]]]),
        )
        generic_bundle = cost_logger.add_cost(
            "Ownership only coin (default NFT1 TP) - one child created", SpendBundle([generic_spend], G2Element())
        )
        result = await sim_client.push_tx(generic_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
        assert len(await sim_client.get_coin_records_by_puzzle_hash(ownership_ph, include_spent_coins=False)) > 0
        await sim.rewind(BLOCK_HEIGHT)

        # Now try an owner update plus royalties
        await sim.farm_block(FAKE_SINGLETON.get_tree_hash())
        await sim.farm_block(FAKE_CAT.get_tree_hash())
        await sim.farm_block(ACS_PH)
        singleton_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(FAKE_SINGLETON.get_tree_hash(), include_spent_coins=False)
        )[0].coin
        cat_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(FAKE_CAT.get_tree_hash(), include_spent_coins=False)
        )[0].coin
        xch_coin = (await sim_client.get_coin_records_by_puzzle_hash(ACS_PH, include_spent_coins=False))[0].coin

        ownership_spend = CoinSpend(
            ownership_coin,
            ownership_puzzle,
            Program.to(
                [[[51, ACS_PH, 1], [-10, FAKE_LAUNCHER_ID, [[100, ACS_PH], [100, FAKE_CAT.get_tree_hash()]], ACS_PH]]]
            ),
        )

        did_announcement_spend = CoinSpend(
            singleton_coin,
            FAKE_SINGLETON,
            Program.to([[[62, FAKE_LAUNCHER_ID]]]),
        )

        expected_announcement_data = Program.to(
            (FAKE_LAUNCHER_ID, [[ROYALTY_ADDRESS, 50, [ROYALTY_ADDRESS]]])
        ).get_tree_hash()
        xch_announcement_spend = CoinSpend(
            xch_coin,
            ACS,
            Program.to([[62, expected_announcement_data]]),
        )

        cat_announcement_spend = CoinSpend(cat_coin, FAKE_CAT, Program.to([[[62, expected_announcement_data]]]))

        # Make sure every combo except all of them fail
        for i in range(1, 3):
            for announcement_combo in itertools.combinations(
                [did_announcement_spend, xch_announcement_spend, cat_announcement_spend], i
            ):
                result = await sim_client.push_tx(SpendBundle([ownership_spend, *announcement_combo], G2Element()))
                assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)

        # Make sure all of them together pass
        full_bundle = cost_logger.add_cost(
            "Ownership only coin (default NFT1 TP) - one child created + update DID + offer CATs + offer XCH",
            SpendBundle(
                [ownership_spend, did_announcement_spend, xch_announcement_spend, cat_announcement_spend], G2Element()
            ),
        )
        result = await sim_client.push_tx(full_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)

        # Finally, make sure we can just clear the DID label off
        new_ownership_puzzle: Program = construct_ownership_layer(
            FAKE_LAUNCHER_ID,
            transfer_program,
            ACS,
        )
        new_ownership_ph: bytes32 = new_ownership_puzzle.get_tree_hash()
        await sim.farm_block(new_ownership_ph)
        new_ownership_coin = (
            await sim_client.get_coin_records_by_puzzle_hash(new_ownership_ph, include_spent_coins=False)
        )[0].coin

        empty_spend = CoinSpend(
            new_ownership_coin,
            new_ownership_puzzle,
            Program.to([[[51, ACS_PH, 1], [-10, [], [], []]]]),
        )
        empty_bundle = cost_logger.add_cost(
            "Ownership only coin (default NFT1 TP) - one child created + clear DID",
            SpendBundle([empty_spend], G2Element()),
        )
        result = await sim_client.push_tx(empty_bundle)
        assert result == (MempoolInclusionStatus.SUCCESS, None)
        await sim.farm_block()
