import pytest

from typing import List, Tuple, Optional, Dict
from blspy import PrivateKey, AugSchemeMPL, G2Element
from clvm.casts import int_to_bytes

from chia.clvm.spend_sim import SpendSim, SimClient
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.util.ints import uint64
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.puzzles.tails import (
    GenesisById,
    GenesisByPuzhash,
    EverythingWithSig,
    DelegatedLimitations,
)

from tests.clvm.test_puzzles import secret_exponent_for_index
from tests.clvm.benchmark_costs import cost_of_spend_bundle

acs = Program.to(1)
acs_ph = acs.get_tree_hash()
NO_LINEAGE_PROOF = LineageProof()


class TestCATLifecycle:
    cost: Dict[str, int] = {}

    @pytest.fixture(scope="function")
    async def setup_sim(self):
        sim = await SpendSim.create()
        sim_client = SimClient(sim)
        await sim.farm_block()
        return sim, sim_client

    async def do_spend(
        self,
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
        cost_str: str = "",
    ):
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
        result = await sim_client.push_tx(
            SpendBundle.aggregate(
                [
                    *additional_spends,
                    spend_bundle,
                    SpendBundle([], agg_sig),  # "Signing" the spend bundle
                ]
            )
        )
        assert result == expected_result
        self.cost[cost_str] = cost_of_spend_bundle(spend_bundle)
        await sim.farm_block()

    @pytest.mark.asyncio()
    async def test_cat_mod(self, setup_sim):
        sim, sim_client = setup_sim

        try:
            tail = Program.to([])
            checker_solution = Program.to([])
            cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, tail.get_tree_hash(), acs)
            cat_ph: bytes32 = cat_puzzle.get_tree_hash()
            await sim.farm_block(cat_ph)
            starting_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(cat_ph))[0].coin

            # Testing the eve spend
            await self.do_spend(
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
                cost_str="Eve Spend",
            )

            # There's 4 total coins at this point. A farming reward and the three children of the spend above.

            # Testing a combination of two
            coins: List[Coin] = [
                record.coin
                for record in (await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))
            ]
            coins = [coins[0], coins[1]]
            await self.do_spend(
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
                cost_str="Two CATs",
            )

            # Testing a combination of three
            coins = [
                record.coin
                for record in (await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))
            ]
            total_amount: uint64 = uint64(sum([c.amount for c in coins]))
            await self.do_spend(
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
                cost_str="Three CATs",
            )

            # Spend with a standard lineage proof
            parent_coin: Coin = coins[0]  # The first one is the one we didn't light on fire
            _, curried_args = cat_puzzle.uncurry()
            _, _, innerpuzzle = curried_args.as_iter()
            lineage_proof = LineageProof(parent_coin.parent_coin_info, innerpuzzle.get_tree_hash(), parent_coin.amount)
            await self.do_spend(
                sim,
                sim_client,
                tail,
                [(await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))[0].coin],
                [lineage_proof],
                [Program.to([[51, acs.get_tree_hash(), total_amount]])],
                (MempoolInclusionStatus.SUCCESS, None),
                reveal_limitations_program=False,
                cost_str="Standard Lineage Check",
            )

            # Melt some value
            await self.do_spend(
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
                cost_str="Melting Value",
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
            await self.do_spend(
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
                cost_str="Mint Value",
            )

        finally:
            await sim.close()

    @pytest.mark.asyncio()
    async def test_complex_spend(self, setup_sim):
        sim, sim_client = setup_sim

        try:
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
            await self.do_spend(
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
                cost_str="Spend two eves",
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
            await self.do_spend(
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
                cost_str="Complex Spend",
            )
        finally:
            await sim.close()

    @pytest.mark.asyncio()
    async def test_genesis_by_id(self, setup_sim):
        sim, sim_client = setup_sim

        try:
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

            await self.do_spend(
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
                cost_str="Genesis by ID",
            )

        finally:
            await sim.close()

    @pytest.mark.asyncio()
    async def test_genesis_by_puzhash(self, setup_sim):
        sim, sim_client = setup_sim

        try:
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

            await self.do_spend(
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
                cost_str="Genesis by Puzhash",
            )

        finally:
            await sim.close()

    @pytest.mark.asyncio()
    async def test_everything_with_signature(self, setup_sim):
        sim, sim_client = setup_sim

        try:
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

            await self.do_spend(
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
                cost_str="Signature Issuance",
            )

            # Test melting value
            coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(cat_ph, include_spent_coins=False))[0].coin
            signature = AugSchemeMPL.sign(
                sk, (int_to_bytes(-1) + coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA)
            )

            await self.do_spend(
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
                cost_str="Signature Melt",
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

            await self.do_spend(
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
                cost_str="Signature Mint",
            )

        finally:
            await sim.close()

    @pytest.mark.asyncio()
    async def test_delegated_tail(self, setup_sim):
        sim, sim_client = setup_sim

        try:
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

            await self.do_spend(
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
                cost_str="Delegated Genesis",
            )

        finally:
            await sim.close()

    def test_cost(self):
        import json
        import logging

        log = logging.getLogger(__name__)
        log.warning(json.dumps(self.cost))
