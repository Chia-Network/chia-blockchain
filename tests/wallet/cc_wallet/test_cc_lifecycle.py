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
from chia.wallet.puzzles.singleton_top_layer import adapt_inner_to_singleton
from chia.wallet.cc_wallet.cc_utils import (
    CC_MOD,
    SpendableCC,
    cc_puzzle_for_inner_puzzle,
    spend_bundle_for_spendable_ccs,
    get_lineage_proof_from_coin_and_puz,
)
from chia.wallet.puzzles.genesis_checkers import (
    GenesisById,
    GenesisByPuzhash,
    EverythingWithSig,
)

from tests.clvm.test_puzzles import secret_exponent_for_index

acs = adapt_inner_to_singleton(Program.to(1))
acs_ph = acs.get_tree_hash()


class TestCCLifecycle:
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
        genesis_checker: Program,
        coins: List[Coin],
        lineage_proofs: List[Program],
        inner_solutions: List[Program],
        expected_result: Tuple[MempoolInclusionStatus, Err],
        signatures: Optional[List[G2Element]] = None,
        extra_deltas: Optional[List[int]] = None,
        additional_spends: List[SpendBundle] = [],
    ):
        spendable_cc_list: List[SpendableCC] = []
        for coin, proof in zip(coins, lineage_proofs):
            spendable_cc_list.append(
                SpendableCC(
                    coin,
                    coin.parent_coin_info,  # This doesn't matter, so we'll just use an available 32 byte value
                    acs,
                    proof,
                )
            )

        spend_bundle: SpendBundle = spend_bundle_for_spendable_ccs(
            CC_MOD,
            genesis_checker,
            spendable_cc_list,
            inner_solutions,
            sigs=signatures,
            extra_deltas=extra_deltas,
        )
        result = await sim_client.push_tx(SpendBundle.aggregate([*additional_spends, spend_bundle]))
        assert result == expected_result
        await sim.farm_block()

    @pytest.mark.asyncio()
    async def test_cc_mod(self, setup_sim):
        sim, sim_client = setup_sim

        try:
            genesis_checker = Program.to([])
            checker_solution = Program.to((0, []))
            cc_puzzle: Program = cc_puzzle_for_inner_puzzle(CC_MOD, genesis_checker, acs)
            cc_ph: bytes32 = cc_puzzle.get_tree_hash()
            await sim.farm_block(cc_ph)
            starting_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(cc_ph))[0].coin

            # Testing the eve spend
            await self.do_spend(
                sim,
                sim_client,
                genesis_checker,
                [starting_coin],
                [checker_solution],
                [
                    Program.to(
                        [
                            [51, acs.get_tree_hash(), starting_coin.amount - 3],
                            [51, acs.get_tree_hash(), 1],
                            [51, acs.get_tree_hash(), 2],
                        ]
                    )
                ],
                (MempoolInclusionStatus.SUCCESS, None),
            )

            # There's 4 total coins at this point. A farming reward and the three children of the spend above.

            # Testing a combination of two
            coins: List[Coin] = [
                record.coin
                for record in (await sim_client.get_coin_records_by_puzzle_hash(cc_ph, include_spent_coins=False))
            ]
            coins = [coins[0], coins[1]]
            await self.do_spend(
                sim,
                sim_client,
                genesis_checker,
                coins,
                [checker_solution] * 2,
                [Program.to([[51, acs.get_tree_hash(), coins[0].amount + coins[1].amount]]), Program.to([])],
                (MempoolInclusionStatus.SUCCESS, None),
            )

            # Testing a combination of three
            coins = [
                record.coin
                for record in (await sim_client.get_coin_records_by_puzzle_hash(cc_ph, include_spent_coins=False))
            ]
            total_amount: uint64 = uint64(sum([c.amount for c in coins]))
            await self.do_spend(
                sim,
                sim_client,
                genesis_checker,
                coins,
                [checker_solution] * 3,
                [Program.to([[51, acs.get_tree_hash(), total_amount]]), Program.to([]), Program.to([])],
                (MempoolInclusionStatus.SUCCESS, None),
            )

            # Spend with a standard lineage proof
            parent_coin: Coin = coins[0]  # The first one is the one we didn't light on fire
            lineage_proof: Program = get_lineage_proof_from_coin_and_puz(parent_coin, cc_puzzle)
            await self.do_spend(
                sim,
                sim_client,
                genesis_checker,
                [(await sim_client.get_coin_records_by_puzzle_hash(cc_ph, include_spent_coins=False))[0].coin],
                [lineage_proof],
                [Program.to([[51, acs.get_tree_hash(), total_amount]])],
                (MempoolInclusionStatus.SUCCESS, None),
            )

            # Melt some value
            await self.do_spend(
                sim,
                sim_client,
                genesis_checker,
                [(await sim_client.get_coin_records_by_puzzle_hash(cc_ph, include_spent_coins=False))[0].coin],
                [checker_solution],
                [Program.to([[51, acs.get_tree_hash(), total_amount - 1]])],
                (MempoolInclusionStatus.SUCCESS, None),
                extra_deltas=[-1],
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
                genesis_checker,
                [(await sim_client.get_coin_records_by_puzzle_hash(cc_ph, include_spent_coins=False))[0].coin],
                [checker_solution],
                [Program.to([[51, acs.get_tree_hash(), total_amount]])],  # We subtracted 1 last time so it's normal now
                (MempoolInclusionStatus.SUCCESS, None),
                extra_deltas=[1],
                additional_spends=[acs_bundle],
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
            genesis_checker: Program = GenesisById.create(starting_coin.name())
            cc_puzzle: Program = cc_puzzle_for_inner_puzzle(CC_MOD, genesis_checker, acs)
            cc_ph: bytes32 = cc_puzzle.get_tree_hash()

            await sim_client.push_tx(
                SpendBundle(
                    [CoinSpend(starting_coin, standard_acs, Program.to([[51, cc_ph, starting_coin.amount]]))],
                    G2Element(),
                )
            )
            await sim.farm_block()

            await self.do_spend(
                sim,
                sim_client,
                genesis_checker,
                [(await sim_client.get_coin_records_by_puzzle_hash(cc_ph, include_spent_coins=False))[0].coin],
                [GenesisById.proof()],
                [Program.to([[51, acs.get_tree_hash(), starting_coin.amount]])],
                (MempoolInclusionStatus.SUCCESS, None),
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
            genesis_checker: Program = GenesisByPuzhash.create(starting_coin.puzzle_hash)
            cc_puzzle: Program = cc_puzzle_for_inner_puzzle(CC_MOD, genesis_checker, acs)
            cc_ph: bytes32 = cc_puzzle.get_tree_hash()

            await sim_client.push_tx(
                SpendBundle(
                    [CoinSpend(starting_coin, standard_acs, Program.to([[51, cc_ph, starting_coin.amount]]))],
                    G2Element(),
                )
            )
            await sim.farm_block()

            await self.do_spend(
                sim,
                sim_client,
                genesis_checker,
                [(await sim_client.get_coin_records_by_puzzle_hash(cc_ph, include_spent_coins=False))[0].coin],
                [GenesisByPuzhash.proof(starting_coin)],
                [Program.to([[51, acs.get_tree_hash(), starting_coin.amount]])],
                (MempoolInclusionStatus.SUCCESS, None),
            )

        finally:
            await sim.close()

    @pytest.mark.asyncio()
    async def test_everything_with_signature(self, setup_sim):
        sim, sim_client = setup_sim

        try:
            sk = PrivateKey.from_bytes(secret_exponent_for_index(1).to_bytes(32, "big"))
            genesis_checker: Program = EverythingWithSig.create(sk.get_g1())
            cc_puzzle: Program = cc_puzzle_for_inner_puzzle(CC_MOD, genesis_checker, acs)
            cc_ph: bytes32 = cc_puzzle.get_tree_hash()
            await sim.farm_block(cc_ph)

            # Test eve spend
            # We don't sign any message data because CLVM 0 translates to b'' apparently
            starting_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(cc_ph))[0].coin
            signature: G2Element = AugSchemeMPL.sign(
                sk, (starting_coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA)
            )

            await self.do_spend(
                sim,
                sim_client,
                genesis_checker,
                [starting_coin],
                [EverythingWithSig.proof()],
                [Program.to([[51, acs.get_tree_hash(), starting_coin.amount]])],
                (MempoolInclusionStatus.SUCCESS, None),
                signatures=[signature],
            )

            # Test melting value
            coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(cc_ph, include_spent_coins=False))[0].coin
            signature = AugSchemeMPL.sign(
                sk, (int_to_bytes(-1) + coin.name() + sim.defaults.AGG_SIG_ME_ADDITIONAL_DATA)
            )

            await self.do_spend(
                sim,
                sim_client,
                genesis_checker,
                [coin],
                [EverythingWithSig.proof()],
                [Program.to([[51, acs.get_tree_hash(), coin.amount - 1]])],
                (MempoolInclusionStatus.SUCCESS, None),
                extra_deltas=[-1],
                signatures=[signature],
            )

            # Test minting value
            coin = (await sim_client.get_coin_records_by_puzzle_hash(cc_ph, include_spent_coins=False))[0].coin
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
                genesis_checker,
                [coin],
                [EverythingWithSig.proof()],
                [Program.to([[51, acs.get_tree_hash(), coin.amount + 1]])],
                (MempoolInclusionStatus.SUCCESS, None),
                extra_deltas=[1],
                signatures=[signature],
                additional_spends=[acs_bundle],
            )

        finally:
            await sim.close()
