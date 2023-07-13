from __future__ import annotations

from typing import Dict, List, Tuple

import pytest
from blspy import G2Element

from chia.clvm.spend_sim import CostLogger, sim_and_client
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.util.merkle_utils import build_merkle_tree, build_merkle_tree_from_binary_tree, simplify_merkle_proof

GRAFTROOT_MOD = load_clvm("graftroot_dl_offers.clsp")

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
async def test_graftroot(cost_logger: CostLogger) -> None:
    async with sim_and_client() as (sim, sim_client):
        # Create the coin we're testing
        all_values: List[bytes32] = [bytes32([x] * 32) for x in range(0, 100)]
        root, proofs = build_merkle_tree(all_values)
        p2_conditions = Program.to((1, [[51, ACS_PH, 0]]))  # An coin to create to make sure this hits the blockchain
        desired_key_values = ((bytes32([0] * 32), bytes32([1] * 32)), (bytes32([7] * 32), bytes32([8] * 32)))
        desired_row_hashes: List[bytes32] = [build_merkle_tree_from_binary_tree(kv)[0] for kv in desired_key_values]
        fake_struct: Program = Program.to((ACS_PH, NIL_PH))
        graftroot_puzzle: Program = GRAFTROOT_MOD.curry(
            # Do everything twice to test depending on multiple singleton updates
            p2_conditions,
            [fake_struct, fake_struct],
            [ACS_PH, ACS_PH],
            [desired_row_hashes, desired_row_hashes],
        )
        await sim.farm_block(graftroot_puzzle.get_tree_hash())
        graftroot_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(graftroot_puzzle.get_tree_hash()))[
            0
        ].coin

        # Build some merkle trees that won't satidy the requirements
        def filter_all(values: List[bytes32]) -> List[bytes32]:
            return [h for i, h in enumerate(values) if (h, values[min(i, i + 1)]) not in desired_key_values]

        def filter_to_only_one(values: List[bytes32]) -> List[bytes32]:
            return [h for i, h in enumerate(values) if (h, values[min(i, i + 1)]) not in desired_key_values[1:]]

        # And one that will
        def filter_none(values: List[bytes32]) -> List[bytes32]:
            return values

        for list_filter in (filter_all, filter_to_only_one, filter_none):
            # Create the "singleton"
            filtered_values = list_filter(all_values)
            root, proofs = build_merkle_tree(filtered_values)
            filtered_row_hashes: Dict[bytes32, Tuple[int, List[bytes32]]] = {
                simplify_merkle_proof(v, (proofs[v][0], [proofs[v][1][0]])): (proofs[v][0] >> 1, proofs[v][1][1:])
                for v in filtered_values
            }
            fake_puzzle: Program = ACS.curry(fake_struct, ACS.curry(ACS_PH, (root, None), NIL_PH, None))
            await sim.farm_block(fake_puzzle.get_tree_hash())
            fake_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(fake_puzzle.get_tree_hash()))[0].coin

            # Create the spend
            fake_spend = CoinSpend(
                fake_coin,
                fake_puzzle,
                Program.to([[[62, "$"]]]),
            )

            proofs_of_inclusion = []
            for row_hash in desired_row_hashes:
                if row_hash in filtered_row_hashes:
                    proofs_of_inclusion.append(filtered_row_hashes[row_hash])
                else:
                    proofs_of_inclusion.append((0, []))

            graftroot_spend = CoinSpend(
                graftroot_coin,
                graftroot_puzzle,
                Program.to(
                    [
                        # Again, everything twice
                        [proofs_of_inclusion] * 2,
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
            if filtered_values == all_values:
                cost_logger.add_cost(
                    "DL Graftroot - fake singleton w/ announce + prove two rows in a DL merkle tree + create one child",
                    final_bundle,
                )
                assert result == (MempoolInclusionStatus.SUCCESS, None)
                # clear the mempool
                same_height = sim.block_height
                await sim.farm_block()
                assert len(await sim_client.get_coin_records_by_puzzle_hash(ACS_PH)) > 0
                await sim.rewind(same_height)

                # try with a bad merkle root announcement
                new_fake_spend = CoinSpend(
                    fake_coin,
                    ACS.curry(fake_struct, ACS.curry(ACS_PH, (bytes32([0] * 32), None), None, None)),
                    Program.to([[[62, "$"]]]),
                )
                new_final_bundle = SpendBundle([new_fake_spend, graftroot_spend], G2Element())
                result = await sim_client.push_tx(new_final_bundle)
                assert result == (MempoolInclusionStatus.FAILED, Err.ASSERT_ANNOUNCE_CONSUMED_FAILED)
            else:
                assert result == (MempoolInclusionStatus.FAILED, Err.GENERATOR_RUNTIME_ERROR)
                with pytest.raises(ValueError, match="clvm raise"):
                    graftroot_puzzle.run(graftroot_spend.solution.to_program())
