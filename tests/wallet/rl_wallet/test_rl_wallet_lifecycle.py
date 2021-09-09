import pytest

from typing import Optional
from blspy import PrivateKey, G2Element, G1Element

from chia.clvm.spend_sim import SpendSim, SimClient
from chia.clvm.singletons.singleton_drivers import MELT_CONDITION
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.program import Program, INFINITE_COST
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from chia.types.coin_record import CoinRecord
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.util.errors import Err
from chia.util.ints import uint64, uint32
from chia.wallet.rl_wallet.rl_wallet_drivers import RLWalletState
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    calculate_synthetic_secret_key,
    DEFAULT_HIDDEN_PUZZLE_HASH,
)

from tests.clvm.test_puzzles import secret_exponent_for_index
from tests.clvm.benchmark_costs import cost_of_spend_bundle


class TestRlWalletLifecycle:
    cost = {}

    @pytest.fixture(scope="function")
    async def setup(self):
        sim = await SpendSim.create()
        sim_client = SimClient(sim)

        anyone_can_spend = Program.to(1)
        acs_ph: bytes32 = anyone_can_spend.get_tree_hash()

        await sim.farm_block(acs_ph)
        farmed_coin: Coin = (await sim_client.get_coin_records_by_puzzle_hash(acs_ph))[0].coin

        user_sk = PrivateKey.from_bytes(secret_exponent_for_index(0).to_bytes(32, "big"))
        admin_sk = PrivateKey.from_bytes(secret_exponent_for_index(1).to_bytes(32, "big"))

        def pk_to_sk(pk: G1Element) -> Optional[PrivateKey]:
            if pk == calculate_synthetic_secret_key(user_sk, DEFAULT_HIDDEN_PUZZLE_HASH).get_g1():
                return calculate_synthetic_secret_key(user_sk, DEFAULT_HIDDEN_PUZZLE_HASH)
            elif pk == calculate_synthetic_secret_key(admin_sk, DEFAULT_HIDDEN_PUZZLE_HASH).get_g1():
                return calculate_synthetic_secret_key(admin_sk, DEFAULT_HIDDEN_PUZZLE_HASH)
            else:
                return None

        wallet_drivers = RLWalletState()
        wallet_drivers.set_initial_withdrawal_settings(  # 500 mojos per block, 10000 cap, no initial credit
            500,
            1,
            10000,
            0,
            sim.block_height,
        )
        wallet_drivers.set_standard_custody_settings(user_sk.get_g1(), admin_sk.get_g1())
        starting_amount: uint64 = 10000005
        conditions, launcher_coin_spend = wallet_drivers.create_launch_spend(farmed_coin, starting_amount)

        spend_bundle = SpendBundle(
            [
                CoinSpend(
                    farmed_coin,
                    anyone_can_spend,
                    Program.to(conditions),
                ),
                launcher_coin_spend,
            ],
            G2Element(),
        )
        self.cost["Cost to launch"] = cost_of_spend_bundle(spend_bundle)

        results = await sim_client.push_tx(spend_bundle)
        assert results[0] == MempoolInclusionStatus.SUCCESS
        await sim.farm_block()

        wallet_drivers.set_initial_singleton_settings(launcher_coin_spend)

        starting_coin_record: CoinRecord = (
            await sim_client.get_coin_records_by_puzzle_hash(
                wallet_drivers.create_full_puzzle().get_tree_hash(),
                include_spent_coins=False,
            )
        )[0]

        starting_coin: Coin = starting_coin_record.coin
        confirmation_block: uint32 = starting_coin_record.confirmed_block_index

        return (
            sim,
            sim_client,
            wallet_drivers,
            user_sk,
            admin_sk,
            pk_to_sk,
            starting_coin,
            starting_amount,
            confirmation_block,
        )

    @pytest.mark.asyncio
    async def test_user_withdrawal(self, setup):
        (
            sim,
            sim_client,
            wallet_drivers,
            user_sk,
            admin_sk,
            pk_to_sk,
            starting_coin,
            starting_amount,
            confirmation_block,
        ) = setup
        try:

            await sim.farm_block()
            await sim.farm_block()

            delegated_puzzle = Program.to(
                (1, [[51, wallet_drivers.user_inner_puzzle.get_tree_hash(), starting_amount - 10]])
            )
            user_spend: CoinSpend = wallet_drivers.create_user_spend(
                starting_coin, confirmation_block + 2, delegated_puzzle, []
            )
            spend_bundle: SpendBundle = await sign_coin_spends(
                [user_spend],
                pk_to_sk,
                DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
                INFINITE_COST,
            )
            self.cost["Cost of user withdrawal"] = cost_of_spend_bundle(spend_bundle)
            results = await sim_client.push_tx(spend_bundle)
            assert results[0] == MempoolInclusionStatus.SUCCESS
            await sim.farm_block()

            # Gotta do it twice to make sure the state change works
            wallet_drivers.update_state_for_coin_spend(user_spend)

            await sim.farm_block()
            await sim.farm_block()

            next_coin: Coin = (
                await sim_client.get_coin_records_by_puzzle_hash(
                    wallet_drivers.create_full_puzzle().get_tree_hash(),
                    include_spent_coins=False,
                )
            )[0].coin
            delegated_puzzle = Program.to(
                (1, [[51, wallet_drivers.user_inner_puzzle.get_tree_hash(), starting_amount - 20]])
            )
            user_spend: CoinSpend = wallet_drivers.create_user_spend(next_coin, sim.block_height, delegated_puzzle, [])
            spend_bundle: SpendBundle = await sign_coin_spends(
                [user_spend],
                pk_to_sk,
                DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
                INFINITE_COST,
            )
            results = await sim_client.push_tx(spend_bundle)
            assert results[0] == MempoolInclusionStatus.SUCCESS
            await sim.farm_block()

            wallet_drivers.update_state_for_coin_spend(user_spend)
        finally:
            await sim.close()

    @pytest.mark.asyncio
    async def test_admin_withdrawal(self, setup):
        (
            sim,
            sim_client,
            wallet_drivers,
            user_sk,
            admin_sk,
            pk_to_sk,
            starting_coin,
            starting_amount,
            confirmation_block,
        ) = setup
        try:
            # This test is very similar to the one above.
            # The differences were in annoying ways so it made some sense to do a bit of code duplication.

            await sim.farm_block()

            delegated_puzzle = Program.to(
                (1, [[51, wallet_drivers.admin_inner_puzzle.get_tree_hash(), starting_amount - 10]])
            )
            admin_spend: CoinSpend = wallet_drivers.create_admin_spend(starting_coin, delegated_puzzle, [])
            spend_bundle: SpendBundle = await sign_coin_spends(
                [admin_spend],
                pk_to_sk,
                DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
                INFINITE_COST,
            )
            self.cost["Cost of admin withdrawal"] = cost_of_spend_bundle(spend_bundle)
            results = await sim_client.push_tx(spend_bundle)
            assert results[0] == MempoolInclusionStatus.SUCCESS
            await sim.farm_block()

            # Gotta do it twice to make sure the state change works
            wallet_drivers.update_state_for_coin_spend(admin_spend)

            await sim.farm_block()

            next_coin: Coin = (
                await sim_client.get_coin_records_by_puzzle_hash(
                    wallet_drivers.create_full_puzzle().get_tree_hash(),
                    include_spent_coins=False,
                )
            )[0].coin
            delegated_puzzle = Program.to(
                (1, [[51, wallet_drivers.admin_inner_puzzle.get_tree_hash(), starting_amount - 20]])
            )
            admin_spend: CoinSpend = wallet_drivers.create_admin_spend(next_coin, delegated_puzzle, [])
            spend_bundle: SpendBundle = await sign_coin_spends(
                [admin_spend],
                pk_to_sk,
                DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
                INFINITE_COST,
            )
            results = await sim_client.push_tx(spend_bundle)
            assert results[0] == MempoolInclusionStatus.SUCCESS
            await sim.farm_block()

            wallet_drivers.update_state_for_coin_spend(admin_spend)
        finally:
            await sim.close()

    @pytest.mark.asyncio
    async def test_user_contribution(self, setup):
        (
            sim,
            sim_client,
            wallet_drivers,
            user_sk,
            admin_sk,
            pk_to_sk,
            starting_coin,
            starting_amount,
            confirmation_block,
        ) = setup
        try:

            await sim.farm_block(Program.to(1).get_tree_hash())
            contribution_coin: Coin = (
                await sim_client.get_coin_records_by_puzzle_hash(
                    Program.to(1).get_tree_hash(),
                    include_spent_coins=False,
                )
            )[0].coin

            delegated_puzzle = Program.to(
                (1, [[51, wallet_drivers.user_inner_puzzle.get_tree_hash(), starting_amount + 10]])
            )
            user_spend: CoinSpend = wallet_drivers.create_user_spend(
                starting_coin, 0, delegated_puzzle, [] # Using a block height of zero so that no curried args change
            )
            contribution_spend = CoinSpend(
                contribution_coin,
                Program.to(1),
                Program.to([]),
            )
            spend_bundle: SpendBundle = await sign_coin_spends(
                [user_spend, contribution_spend],
                pk_to_sk,
                DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
                INFINITE_COST,
            )
            self.cost["Cost of user contribution"] = cost_of_spend_bundle(spend_bundle)
            results = await sim_client.push_tx(spend_bundle)
            assert results[0] == MempoolInclusionStatus.SUCCESS
            await sim.farm_block()

            # Doing the same search twice to make sure the state doesn't change at all when we update state
            # Importantly, it would have updated if we had specified a later block (user credit)
            assert (
                len(
                    (
                        await sim_client.get_coin_records_by_puzzle_hash(
                            wallet_drivers.create_full_puzzle().get_tree_hash(),
                            include_spent_coins=False,
                        )
                    )
                )
                == 1
            )
            wallet_drivers.update_state_for_coin_spend(user_spend)
            assert (
                len(
                    (
                        await sim_client.get_coin_records_by_puzzle_hash(
                            wallet_drivers.create_full_puzzle().get_tree_hash(),
                            include_spent_coins=False,
                        )
                    )
                )
                == 1
            )

        finally:
            await sim.close()

    @pytest.mark.asyncio
    async def test_admin_contribution(self, setup):
        (
            sim,
            sim_client,
            wallet_drivers,
            user_sk,
            admin_sk,
            pk_to_sk,
            starting_coin,
            starting_amount,
            confirmation_block,
        ) = setup
        try:
            # This test is very similar to the one above.
            # The differences were in annoying ways so it made some sense to do a bit of code duplication.

            await sim.farm_block(Program.to(1).get_tree_hash())
            contribution_coin: Coin = (
                await sim_client.get_coin_records_by_puzzle_hash(
                    Program.to(1).get_tree_hash(),
                    include_spent_coins=False,
                )
            )[0].coin

            delegated_puzzle = Program.to(
                (1, [[51, wallet_drivers.admin_inner_puzzle.get_tree_hash(), starting_amount + 10]])
            )
            admin_spend: CoinSpend = wallet_drivers.create_admin_spend(starting_coin, delegated_puzzle, [])
            contribution_spend = CoinSpend(
                contribution_coin,
                Program.to(1),
                Program.to([]),
            )
            spend_bundle: SpendBundle = await sign_coin_spends(
                [admin_spend, contribution_spend],
                pk_to_sk,
                DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
                INFINITE_COST,
            )
            self.cost["Cost of admin contribution"] = cost_of_spend_bundle(spend_bundle)
            results = await sim_client.push_tx(spend_bundle)
            assert results[0] == MempoolInclusionStatus.SUCCESS
            await sim.farm_block()

            # Doing the same search twice to make sure the state doesn't change at all when we update state
            # Importantly, it would have updated if we had specified a later block (user credit)
            assert (
                len(
                    (
                        await sim_client.get_coin_records_by_puzzle_hash(
                            wallet_drivers.create_full_puzzle().get_tree_hash(),
                            include_spent_coins=False,
                        )
                    )
                )
                == 1
            )
            wallet_drivers.update_state_for_coin_spend(admin_spend)
            assert (
                len(
                    (
                        await sim_client.get_coin_records_by_puzzle_hash(
                            wallet_drivers.create_full_puzzle().get_tree_hash(),
                            include_spent_coins=False,
                        )
                    )
                )
                == 1
            )

        finally:
            await sim.close()

    @pytest.mark.asyncio
    async def test_who_can_melt(self, setup):
        (
            sim,
            sim_client,
            wallet_drivers,
            user_sk,
            admin_sk,
            pk_to_sk,
            starting_coin,
            starting_amount,
            confirmation_block,
        ) = setup
        try:

            await sim.farm_block()
            await sim.farm_block()

            # First, we're going to make sure it successfully runs the program
            delegated_puzzle = Program.to(
                (1, [[51, wallet_drivers.user_inner_puzzle.get_tree_hash(), starting_amount - 10]])
            )
            user_spend: CoinSpend = wallet_drivers.create_user_spend(
                starting_coin, confirmation_block + 2, delegated_puzzle, []
            )
            spend_bundle = SpendBundle(
                [user_spend],
                G2Element(),
            )
            results = await sim_client.push_tx(spend_bundle)
            assert results[0] == MempoolInclusionStatus.FAILED
            assert results[1] == Err.BAD_AGGREGATE_SIGNATURE  # Checking for this error saves us a rewind

            # Then we're going to only change to a melt condition and make sure that fails
            delegated_puzzle = Program.to((1, [MELT_CONDITION]))
            user_spend: CoinSpend = wallet_drivers.create_user_spend(
                starting_coin, confirmation_block + 2, delegated_puzzle, []
            )
            spend_bundle = SpendBundle(
                [user_spend],
                G2Element(),
            )
            results = await sim_client.push_tx(spend_bundle)
            assert results[0] == MempoolInclusionStatus.FAILED
            assert results[1] == Err.GENERATOR_RUNTIME_ERROR

            # Then we're going to do it with the admin information and that should work
            delegated_puzzle = Program.to((1, [MELT_CONDITION]))
            admin_spend: CoinSpend = wallet_drivers.create_admin_spend(starting_coin, delegated_puzzle, [])
            spend_bundle: SpendBundle = await sign_coin_spends(
                [admin_spend],
                pk_to_sk,
                DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA,
                INFINITE_COST,
            )
            self.cost["Cost of admin melt"] = cost_of_spend_bundle(spend_bundle)
            results = await sim_client.push_tx(spend_bundle)
            assert results[0] == MempoolInclusionStatus.SUCCESS
        finally:
            await sim.close()

    def test_cost(self):
        import json
        import logging
        log = logging.getLogger(__name__)
        log.warning(json.dumps(self.cost))