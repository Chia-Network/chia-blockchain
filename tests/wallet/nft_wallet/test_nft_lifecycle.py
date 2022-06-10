import pytest

from blspy import G2Element
from typing import List, Tuple

from chia.clvm.spend_sim import SpendSim, SimClient
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.wallet.nft_wallet.nft_puzzles import (
    create_nft_layer_puzzle_with_curry_params,
    metadata_to_program,
    NFT_METADATA_UPDATER,
)

ACS = Program.to(1)
ACS_PH = ACS.get_tree_hash()


@pytest.mark.asyncio()
@pytest.mark.parametrize("metadata_updater", ["default"])
async def test_state_layer(setup_sim: Tuple[SpendSim, SimClient], metadata_updater: str) -> None:
    sim, sim_client = setup_sim

    try:
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
        generic_bundle = SpendBundle([generic_spend], G2Element())

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
            update_bundle = SpendBundle([update_spend], G2Element())
            result = await sim_client.push_tx(update_bundle)
            assert result == (MempoolInclusionStatus.SUCCESS, None)
            await sim.farm_block()
            state_layer_puzzle = create_nft_layer_puzzle_with_curry_params(metadata, METADATA_UPDATER_PUZZLE_HASH, ACS)
    finally:
        await sim.close()  # type: ignore
