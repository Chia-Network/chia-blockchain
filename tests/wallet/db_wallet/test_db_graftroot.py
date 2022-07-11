import pytest

from blspy import G2Element
from typing import List, Tuple

from chia.clvm.spend_sim import SimClient, SpendSim
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.util.merkle_utils import build_merkle_tree

GRAFTROOT_MOD = load_clvm("graftroot_dl_offers.clvm")

# Always returns the last value
# (mod solution
#
#   (defun recurse (solution last_value)
#     (if solution
#         (recurse (r solution) (f solution))
#         last_value
#     )
#   )
#
#   (recurse solution ())
# )
ACS = Program.fromhex(
    "ff02ffff01ff02ff02ffff04ff02ffff04ff03ffff01ff8080808080ffff04ffff01ff02ffff03ff05ffff01ff02ff02ffff04ff02ffff04ff0dffff04ff09ff8080808080ffff010b80ff0180ff018080"  # noqa
)
ACS_PH = ACS.get_tree_hash()

NIL_PH = Program.to(None).get_tree_hash()


@pytest.mark.asyncio
async def test_graftroot(setup_sim: Tuple[SpendSim, SimClient]) -> None:
    sim, sim_client = setup_sim
    try:
        # Create the coin we're testing
        all_row_hashes: List[bytes32] = [bytes32([x] * 32) for x in range(0, 100)]
        p2_conditions = Program.to((1, [[51, ACS_PH, 0]]))  # An coin to create to make sure this hits the blockchain
        desired_indexes = (13, 17)
        desired_row_hashes: List[bytes32] = [h for i, h in enumerate(all_row_hashes) if i in desired_indexes]
        graftroot_puzzle: Program = GRAFTROOT_MOD.curry(
            # Do everything twice to test depending on multiple singleton updates
            p2_conditions,
            [ACS_PH, ACS_PH],
            [ACS_PH, ACS_PH],
            [desired_row_hashes, desired_row_hashes],
        )
        await sim.farm_block(graftroot_puzzle.get_tree_hash())
        graftroot_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(graftroot_puzzle.get_tree_hash()))[
            0
        ].coin

        # Build some merkle trees that won't satidy the requirements
        def filter_all(hash_list: List[bytes32]) -> List[bytes32]:
            return [h for i, h in enumerate(hash_list) if i not in desired_indexes]

        def filter_to_only_one(hash_list: List[bytes32]) -> List[bytes32]:
            return [h for i, h in enumerate(hash_list) if i not in desired_indexes[1:]]

        # And one that will
        def filter_none(hash_list: List[bytes32]) -> List[bytes32]:
            return hash_list

        for list_filter in (filter_all, filter_to_only_one, filter_none):
            # Create the "singleton"
            filtered_hashes = list_filter(all_row_hashes)
            root, proofs = build_merkle_tree(filtered_hashes)
            fake_puzzle: Program = ACS.curry(ACS.curry((root, None), None, None))
            await sim.farm_block(fake_puzzle.get_tree_hash())
            fake_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(fake_puzzle.get_tree_hash()))[0].coin

            # Create the spend
            fake_spend = CoinSpend(
                fake_coin,
                fake_puzzle,
                Program.to([[[62, "$"]]]),
            )

            graftroot_spend = CoinSpend(
                graftroot_coin,
                graftroot_puzzle,
                Program.to(
                    [
                        # Again, everything twice
                        [[proofs[filtered_hashes[i]] for i in desired_indexes]] * 2,
                        [(root, None), (root, None)],
                        [NIL_PH, NIL_PH],
                        [NIL_PH, NIL_PH],
                        [],
                    ]
                ),
            )

            final_bundle = SpendBundle([fake_spend, graftroot_spend], G2Element())
            result = await sim_client.push_tx(final_bundle)

            # If this is the satisfactory merkle tree
            if filtered_hashes == all_row_hashes:
                assert result == (MempoolInclusionStatus.SUCCESS, None)
                # clear the mempool
                same_height = sim.block_height
                await sim.farm_block()
                assert len(await sim_client.get_coin_records_by_puzzle_hash(ACS_PH)) > 0
                await sim.rewind(same_height)

                # try with a bad merkle root announcement
                new_fake_spend = CoinSpend(
                    fake_coin,
                    ACS.curry(ACS.curry((bytes32([0] * 32), None), None, None)),
                    Program.to([[[62, "$"]]]),
                )
                new_final_bundle = SpendBundle([new_fake_spend, graftroot_spend], G2Element())
                result = await sim_client.push_tx(new_final_bundle)
                assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)
            else:
                assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)
                with pytest.raises(ValueError, match="clvm raise"):
                    graftroot_puzzle.run(graftroot_spend.solution.to_program())
    finally:
        await sim.close()  # type: ignore[no-untyped-call]
