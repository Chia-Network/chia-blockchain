from __future__ import annotations

from typing import List, Optional, Tuple

import pytest
from blspy import AugSchemeMPL, G2Element, PrivateKey
from clvm.casts import int_to_bytes

from chia.clvm.spend_sim import CostLogger, SimClient, SpendSim, sim_and_client
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.errors import Err
from chia.util.ints import uint64
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.puzzles.tails import DelegatedLimitations, EverythingWithSig, GenesisById, GenesisByPuzhash
from tests.clvm.benchmark_costs import cost_of_spend_bundle
from tests.clvm.test_puzzles import secret_exponent_for_index

acs = Program.to(1)
acs_ph = acs.get_tree_hash()
NO_LINEAGE_PROOF = LineageProof()


async def do_spend(
    sim: SpendSim,
    sim_client: SimClient,
    tail: Program,
    coins: List[Coin],
    lineage_proofs: List[Program],
    inner_solutions: List[Program],
    expected_result: Tuple[MempoolInclusionStatus, Err],
    reveal_limitations_program: bool = True,
    signatures: List[G2Element] = [],
    extra_deltas: Optional[List[int]] = None,
    additional_spends: List[SpendBundle] = [],
    limitations_solutions: Optional[List[Program]] = None,
    cost_logger: Optional[CostLogger] = None,
    cost_log_msg: str = "",
) -> int:
    if limitations_solutions is None:
        limitations_solutions = [Program.to([])] * len(coins)
    if extra_deltas is None:
        extra_deltas = [0] * len(coins)

    spendable_cat_list: List[SpendableCAT] = []
    for coin, innersol, proof, limitations_solution, extra_delta in zip(
        coins, inner_solutions, lineage_proofs, limitations_solutions, extra_deltas
    ):
        spendable_cat_list.append(
            SpendableCAT(
                coin,
                tail.get_tree_hash(),
                acs,
                innersol,
                limitations_solution=limitations_solution,
                lineage_proof=proof,
                extra_delta=extra_delta,
                limitations_program_reveal=tail if reveal_limitations_program else Program.to([]),
            )
        )

    spend_bundle: SpendBundle = unsigned_spend_bundle_for_spendable_cats(
        CAT_MOD,
        spendable_cat_list,
    )
    agg_sig = AugSchemeMPL.aggregate(signatures)
    final_bundle = SpendBundle.aggregate(
        [
            *additional_spends,
            spend_bundle,
            SpendBundle([], agg_sig),  # "Signing" the spend bundle
        ]
    )
    if cost_logger is not None:
        final_bundle = cost_logger.add_cost(cost_log_msg, final_bundle)
    result = await sim_client.push_tx(final_bundle)
    assert result == expected_result
    cost = cost_of_spend_bundle(spend_bundle)
    await sim.farm_block()
    return cost


class TestCATLifecycle:
    @pytest.mark.asyncio()
    async def test_cat_mod(self, cost_logger):
        async with sim_and_client() as (sim, sim_client):
            tail = Program.to([])
            checker_solution = Program.to([])
            cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, tail.get_tree_hash(), acs)
            cat_ph: bytes32 = cat_puzzle.get_tree_hash()
            await sim.farm_block(cat_ph)
            starting_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(cat_ph))[0].coin

            # Testing the eve spend
            await do_spend(
                sim,
                sim_client,
                tail,
                [starting_coin],
                [NO_LINEAGE_PROOF],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), starting_coin.amount - 3, [b"memo"]],
                            [51, acs.get_tree_hash(), 1],
                            [51, acs.get_tree_hash(), 2],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    )
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                limitations_solutions=[checker_solution],
                cost_logger=cost_logger,
                cost_log_msg="Cat Eve Spend + create three children (TAIL: ())",
            )

            # There's 4 total coins at this point. A farming reward and the three children of the spend above.

            # Testing a combination of two
            coins: List[Coin] = [
                record.coin
                for record in (await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))
            ]
            coins = [coins[0], coins[1]]
            await do_spend(
                sim,
                sim_client,
                tail,
                coins,
                [NO_LINEAGE_PROOF] * 2,
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), coins[0].amount + coins[1].amount],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    ),
                    Program.to([[51, 0, -113, tail, checker_solution]]),
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                limitations_solutions=[checker_solution] * 2,
                cost_logger=cost_logger,
                cost_log_msg="Cat Spend x2 + create one child (TAIL: ())",
            )

            # Testing a combination of three
            coins = [
                record.coin
                for record in (await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))
            ]
            total_amount: uint64 = uint64(sum([c.amount for c in coins]))
            await do_spend(
                sim,
                sim_client,
                tail,
                coins,
                [NO_LINEAGE_PROOF] * 3,
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), total_amount],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    ),
                    Program.to([[51, 0, -113, tail, checker_solution]]),
                    Program.to([[51, 0, -113, tail, checker_solution]]),
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                limitations_solutions=[checker_solution] * 3,
                cost_logger=cost_logger,
                cost_log_msg="Cat Spend x3 + create one child (TAIL: ())",
            )

            # Spend with a standard lineage proof
            parent_coin: Coin = coins[0]  # The first one is the one we didn't light on fire
            _, curried_args = cat_puzzle.uncurry()
            _, _, innerpuzzle = curried_args.as_iter()
            lineage_proof = LineageProof(parent_coin.parent_coin_info, innerpuzzle.get_tree_hash(), parent_coin.amount)
            await do_spend(
                sim,
                sim_client,
                tail,
                [(await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))[0].coin],
                [lineage_proof],
                [Program.to([[51, acs.get_tree_hash(), total_amount]])],
                (MempoolInclusionStatus.SUCCESS, None),
                reveal_limitations_program=False,
                cost_logger=cost_logger,
                cost_log_msg="Cat Spend + create one child",
            )

            # Melt some value
            await do_spend(
                sim,
                sim_client,
                tail,
                [(await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))[0].coin],
                [NO_LINEAGE_PROOF],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), total_amount - 1],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    )
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                extra_deltas=[-1],
                limitations_solutions=[checker_solution],
                cost_logger=cost_logger,
                cost_log_msg="Cat Spend (Melt) + create one child (TAIL: ())",
            )

            # Mint some value
            temp_p = Program.to(1)
            temp_ph: bytes32 = temp_p.get_tree_hash()
            await sim.farm_block(temp_ph)
            acs_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(temp_ph, include_spent_coins=False))[
                0
            ].coin
            acs_bundle = SpendBundle(
                [
                    CoinSpend(
                        acs_coin,
                        temp_p,
                        Program.to([]),
                    )
                ],
                G2Element(),
            )
            await do_spend(
                sim,
                sim_client,
                tail,
                [(await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))[0].coin],
                [NO_LINEAGE_PROOF],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), total_amount],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    )
                ],  # We subtracted 1 last time so it's normal now
                (MempoolInclusionStatus.SUCCESS, None),
                extra_deltas=[1],
                additional_spends=[acs_bundle],
                limitations_solutions=[checker_solution],
                cost_logger=cost_logger,
                cost_log_msg="ACS burn + Cat Spend (Mint) + create one child (TAIL: ())",
            )

    @pytest.mark.asyncio()
    async def test_complex_spend(self, cost_logger):
        async with sim_and_client() as (sim, sim_client):
            tail = Program.to([])
            checker_solution = Program.to([])
            cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, tail.get_tree_hash(), acs)
            cat_ph: bytes32 = cat_puzzle.get_tree_hash()
            await sim.farm_block(cat_ph)
            await sim.farm_block(cat_ph)

            cat_records = await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False)
            parent_of_mint = cat_records[0].coin
            parent_of_melt = cat_records[1].coin
            eve_to_mint = cat_records[2].coin
            eve_to_melt = cat_records[3].coin

            # Spend two of them to make them non-eve
            await do_spend(
                sim,
                sim_client,
                tail,
                [parent_of_mint, parent_of_melt],
                [NO_LINEAGE_PROOF, NO_LINEAGE_PROOF],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), parent_of_mint.amount],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    ),
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), parent_of_melt.amount],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    ),
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                limitations_solutions=[checker_solution] * 2,
                cost_logger=cost_logger,
                cost_log_msg="Cat Eve Spend x2 + create one child each (TAIL: ())",
            )

            # Make the lineage proofs for the non-eves
            mint_lineage = LineageProof(parent_of_mint.parent_coin_info, acs_ph, parent_of_mint.amount)
            melt_lineage = LineageProof(parent_of_melt.parent_coin_info, acs_ph, parent_of_melt.amount)

            # Find the two new coins
            all_cats = await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False)
            all_cat_coins = [cr.coin for cr in all_cats]
            standard_to_mint = list(filter(lambda cr: cr.parent_coin_info == parent_of_mint.name(), all_cat_coins))[0]
            standard_to_melt = list(filter(lambda cr: cr.parent_coin_info == parent_of_melt.name(), all_cat_coins))[0]

            # Do the complex spend
            # We have both and eve and non-eve doing both minting and melting
            await do_spend(
                sim,
                sim_client,
                tail,
                [eve_to_mint, eve_to_melt, standard_to_mint, standard_to_melt],
                [NO_LINEAGE_PROOF, NO_LINEAGE_PROOF, mint_lineage, melt_lineage],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), eve_to_mint.amount + 13],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    ),
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), eve_to_melt.amount - 21],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    ),
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), standard_to_mint.amount + 21],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    ),
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), standard_to_melt.amount - 13],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    ),
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                limitations_solutions=[checker_solution] * 4,
                extra_deltas=[13, -21, 21, -13],
                cost_logger=cost_logger,
                cost_log_msg="Cat Eve Spend x2 (mint & melt) + Cat Spend x2 (mint & melt) - one child each (TAIL: ())",
            )

    @pytest.mark.asyncio()
    async def test_genesis_by_id(self, cost_logger):
        async with sim_and_client() as (sim, sim_client):
            standard_acs = Program.to(1)
            standard_acs_ph: bytes32 = standard_acs.get_tree_hash()
            await sim.farm_block(standard_acs_ph)

            starting_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(standard_acs_ph))[0].coin
            tail: Program = GenesisById.construct([Program.to(starting_coin.name())])
            checker_solution: Program = GenesisById.solve([], {})
            cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, tail.get_tree_hash(), acs)
            cat_ph: bytes32 = cat_puzzle.get_tree_hash()

            await sim_client.push_tx(
                SpendBundle(
                    [CoinSpend(starting_coin, standard_acs, Program.to([[51, cat_ph, starting_coin.amount]]))],
                    G2Element(),
                )
            )
            await sim.farm_block()

            await do_spend(
                sim,
                sim_client,
                tail,
                [(await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))[0].coin],
                [NO_LINEAGE_PROOF],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), starting_coin.amount],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    )
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                limitations_solutions=[checker_solution],
                cost_logger=cost_logger,
                cost_log_msg="Cat Eve Spend - create one child (TAIL: genesis_by_id)",
            )

    @pytest.mark.asyncio()
    async def test_genesis_by_puzhash(self, cost_logger):
        async with sim_and_client() as (sim, sim_client):
            standard_acs = Program.to(1)
            standard_acs_ph: bytes32 = standard_acs.get_tree_hash()
            await sim.farm_block(standard_acs_ph)

            starting_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(standard_acs_ph))[0].coin
            tail: Program = GenesisByPuzhash.construct([Program.to(starting_coin.puzzle_hash)])
            checker_solution: Program = GenesisByPuzhash.solve([], starting_coin.to_json_dict())
            cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, tail.get_tree_hash(), acs)
            cat_ph: bytes32 = cat_puzzle.get_tree_hash()

            await sim_client.push_tx(
                SpendBundle(
                    [CoinSpend(starting_coin, standard_acs, Program.to([[51, cat_ph, starting_coin.amount]]))],
                    G2Element(),
                )
            )
            await sim.farm_block()

            await do_spend(
                sim,
                sim_client,
                tail,
                [(await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))[0].coin],
                [NO_LINEAGE_PROOF],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), starting_coin.amount],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    )
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                limitations_solutions=[checker_solution],
                cost_logger=cost_logger,
                cost_log_msg="Cat Eve Spend - create one child (TAIL: genesis_by_puzhash)",
            )

    @pytest.mark.asyncio()
    async def test_everything_with_signature(self, cost_logger):
        async with sim_and_client() as (sim, sim_client):
            sk = PrivateKey.from_bytes(secret_exponent_for_index(1).to_bytes(32, "big"))
            tail: Program = EverythingWithSig.construct([Program.to(sk.get_g1())])
            checker_solution: Program = EverythingWithSig.solve([], {})
            cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, tail.get_tree_hash(), acs)
            cat_ph: bytes32 = cat_puzzle.get_tree_hash()
            await sim.farm_block(cat_ph)

            # Test eve spend
            # We don't sign any message data because CLVM 0 translates to b'' apparently
            starting_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(cat_ph))[0].coin
            signature: G2Element = AugSchemeMPL.sign(
                sk, (starting_coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA)
            )

            await do_spend(
                sim,
                sim_client,
                tail,
                [starting_coin],
                [NO_LINEAGE_PROOF],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), starting_coin.amount],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    )
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                limitations_solutions=[checker_solution],
                signatures=[signature],
                cost_logger=cost_logger,
                cost_log_msg="Cat Eve Spend - create one child (TAIL: everything_with_signature)",
            )

            # Test melting value
            coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))[0].coin
            signature = AugSchemeMPL.sign(
                sk, (int_to_bytes(-1) + coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA)
            )

            await do_spend(
                sim,
                sim_client,
                tail,
                [coin],
                [NO_LINEAGE_PROOF],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), coin.amount - 1],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    )
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                extra_deltas=[-1],
                limitations_solutions=[checker_solution],
                signatures=[signature],
                cost_logger=cost_logger,
                cost_log_msg="Cat Spend (Melt) - create one child (TAIL: everything_with_signature)",
            )

            # Test minting value
            coin = (await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))[0].coin
            signature = AugSchemeMPL.sign(sk, (int_to_bytes(1) + coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA))

            # Need something to fund the minting
            temp_p = Program.to(1)
            temp_ph: bytes32 = temp_p.get_tree_hash()
            await sim.farm_block(temp_ph)
            acs_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(temp_ph, include_spent_coins=False))[
                0
            ].coin
            acs_bundle = SpendBundle(
                [
                    CoinSpend(
                        acs_coin,
                        temp_p,
                        Program.to([]),
                    )
                ],
                G2Element(),
            )

            await do_spend(
                sim,
                sim_client,
                tail,
                [coin],
                [NO_LINEAGE_PROOF],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), coin.amount + 1],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    )
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                extra_deltas=[1],
                limitations_solutions=[checker_solution],
                signatures=[signature],
                additional_spends=[acs_bundle],
                cost_logger=cost_logger,
                cost_log_msg="ACS Burn + Cat Spend (Mint) - create one child (TAIL: everything_with_signature)",
            )

    @pytest.mark.asyncio()
    async def test_delegated_tail(self, cost_logger):
        async with sim_and_client() as (sim, sim_client):
            standard_acs = Program.to(1)
            standard_acs_ph: bytes32 = standard_acs.get_tree_hash()
            await sim.farm_block(standard_acs_ph)

            starting_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(standard_acs_ph))[0].coin
            sk = PrivateKey.from_bytes(secret_exponent_for_index(1).to_bytes(32, "big"))
            tail: Program = DelegatedLimitations.construct([Program.to(sk.get_g1())])
            cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, tail.get_tree_hash(), acs)
            cat_ph: bytes32 = cat_puzzle.get_tree_hash()

            await sim_client.push_tx(
                SpendBundle(
                    [CoinSpend(starting_coin, standard_acs, Program.to([[51, cat_ph, starting_coin.amount]]))],
                    G2Element(),
                )
            )
            await sim.farm_block()

            # We're signing a different tail to use here
            name_as_program = Program.to(starting_coin.name())
            new_tail: Program = GenesisById.construct([name_as_program])
            checker_solution: Program = DelegatedLimitations.solve(
                [name_as_program],
                {
                    "signed_program": {
                        "identifier": "genesis_by_id",
                        "args": [str(name_as_program)],
                    },
                    "program_arguments": {},
                },
            )
            signature: G2Element = AugSchemeMPL.sign(sk, new_tail.get_tree_hash())

            await do_spend(
                sim,
                sim_client,
                tail,
                [(await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))[0].coin],
                [NO_LINEAGE_PROOF],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), starting_coin.amount],
                            [51, 0, -113, tail, checker_solution],
                        ]
                    )
                ],
                (MempoolInclusionStatus.SUCCESS, None),
                signatures=[signature],
                limitations_solutions=[checker_solution],
                cost_logger=cost_logger,
                cost_log_msg="Cat Eve Spend - create one child (TAIL: delegated_tail - genesis_by_id)",
            )
