import copy

from typing import List
from unittest import TestCase

from blspy import AugSchemeMPL, G1Element, G2Element, PrivateKey

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64, uint32
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    puzzle_for_pk,
    solution_for_conditions,
    calculate_synthetic_secret_key,
    DEFAULT_HIDDEN_PUZZLE_HASH,
)
from chia.wallet.puzzles.p2_conditions import puzzle_for_conditions
from chia.wallet.puzzles import singleton_top_layer
from chia.pools.pool_wallet_info import PoolState
from chia.pools.pool_puzzles import (
    create_waiting_room_inner_puzzle,
    create_pooling_inner_puzzle,
    create_p2_singleton_puzzle,
    create_absorb_spend,
    create_travel_spend,
    get_most_recent_singleton_coin_from_coin_spend,
    get_delayed_puz_info_from_launcher_spend,
    SINGLETON_MOD_HASH,
    launcher_id_to_p2_puzzle_hash,
    is_pool_singleton_inner_puzzle,
    get_pubkey_from_member_inner_puzzle,
    solution_to_pool_state,
    uncurry_pool_waitingroom_inner_puzzle,
    get_seconds_and_delayed_puzhash_from_p2_singleton_puzzle,
)
from tests.util.key_tool import KeyTool
from tests.clvm.test_puzzles import (
    public_key_for_index,
    secret_exponent_for_index,
)

from tests.clvm.coin_store import CoinStore, CoinTimestamp, BadSpendBundleError

"""
This test suite aims to test:
    - chia.pools.pool_puzzles.py
    - chia.wallet.puzzles.pool_member_innerpuz.clvm
    - chia.wallet.puzzles.pool_waiting_room_innerpuz.clvm
"""


# Helper function
def sign_delegated_puz(del_puz: Program, coin: Coin) -> G2Element:
    synthetic_secret_key: PrivateKey = calculate_synthetic_secret_key(
        PrivateKey.from_bytes(
            secret_exponent_for_index(1).to_bytes(32, "big"),
        ),
        DEFAULT_HIDDEN_PUZZLE_HASH,
    )
    return AugSchemeMPL.sign(
        synthetic_secret_key,
        (del_puz.get_tree_hash() + coin.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA),
    )


class TestPoolPuzzles(TestCase):
    def test_pool_lifecycle(self):
        # START TESTS
        # Generate starting info
        key_lookup = KeyTool()
        sk: PrivateKey = PrivateKey.from_bytes(
            secret_exponent_for_index(1).to_bytes(32, "big"),
        )
        pk: G1Element = G1Element.from_bytes(public_key_for_index(1, key_lookup))
        starting_puzzle: Program = puzzle_for_pk(pk)
        starting_ph: bytes32 = starting_puzzle.get_tree_hash()

        # Get our starting standard coin created
        START_AMOUNT: uint64 = 1023
        coin_db = CoinStore()
        time = CoinTimestamp(10000000, 1)
        coin_db.farm_coin(starting_ph, time, START_AMOUNT)
        starting_coin: Coin = next(coin_db.all_unspent_coins())

        # LAUNCHING
        # Create the escaping inner puzzle
        GENESIS_CHALLENGE = bytes32.fromhex("ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb")
        launcher_coin = singleton_top_layer.generate_launcher_coin(
            starting_coin,
            START_AMOUNT,
        )
        DELAY_TIME = uint64(60800)
        DELAY_PH = starting_ph
        launcher_id = launcher_coin.name()
        relative_lock_height: uint32 = uint32(5000)
        # use a dummy pool state
        pool_state = PoolState(
            owner_pubkey=pk,
            pool_url="",
            relative_lock_height=relative_lock_height,
            state=3,  # farming to pool
            target_puzzle_hash=starting_ph,
            version=1,
        )
        # create a new dummy pool state for travelling
        target_pool_state = PoolState(
            owner_pubkey=pk,
            pool_url="",
            relative_lock_height=relative_lock_height,
            state=2,  # Leaving pool
            target_puzzle_hash=starting_ph,
            version=1,
        )
        # Standard format comment
        comment = Program.to([("p", bytes(pool_state)), ("t", DELAY_TIME), ("h", DELAY_PH)])
        pool_wr_innerpuz: bytes32 = create_waiting_room_inner_puzzle(
            starting_ph,
            relative_lock_height,
            pk,
            launcher_id,
            GENESIS_CHALLENGE,
            DELAY_TIME,
            DELAY_PH,
        )
        pool_wr_inner_hash = pool_wr_innerpuz.get_tree_hash()
        pooling_innerpuz: Program = create_pooling_inner_puzzle(
            starting_ph,
            pool_wr_inner_hash,
            pk,
            launcher_id,
            GENESIS_CHALLENGE,
            DELAY_TIME,
            DELAY_PH,
        )
        # Driver tests
        assert is_pool_singleton_inner_puzzle(pooling_innerpuz)
        assert is_pool_singleton_inner_puzzle(pool_wr_innerpuz)
        assert get_pubkey_from_member_inner_puzzle(pooling_innerpuz) == pk
        # Generating launcher information
        conditions, launcher_coinsol = singleton_top_layer.launch_conditions_and_coinsol(
            starting_coin, pooling_innerpuz, comment, START_AMOUNT
        )
        # Creating solution for standard transaction
        delegated_puzzle: Program = puzzle_for_conditions(conditions)
        full_solution: Program = solution_for_conditions(conditions)
        starting_coinsol = CoinSpend(
            starting_coin,
            starting_puzzle,
            full_solution,
        )
        # Create the spend bundle
        sig: G2Element = sign_delegated_puz(delegated_puzzle, starting_coin)
        spend_bundle = SpendBundle(
            [starting_coinsol, launcher_coinsol],
            sig,
        )
        # Spend it!
        coin_db.update_coin_store_for_spend_bundle(
            spend_bundle,
            time,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            DEFAULT_CONSTANTS.COST_PER_BYTE,
        )
        # Test that we can retrieve the extra data
        assert get_delayed_puz_info_from_launcher_spend(launcher_coinsol) == (DELAY_TIME, DELAY_PH)
        assert solution_to_pool_state(launcher_coinsol) == pool_state

        # TEST TRAVEL AFTER LAUNCH
        # fork the state
        fork_coin_db: CoinStore = copy.deepcopy(coin_db)
        post_launch_coinsol, _ = create_travel_spend(
            launcher_coinsol,
            launcher_coin,
            pool_state,
            target_pool_state,
            GENESIS_CHALLENGE,
            DELAY_TIME,
            DELAY_PH,
        )
        # Spend it!
        fork_coin_db.update_coin_store_for_spend_bundle(
            SpendBundle([post_launch_coinsol], G2Element()),
            time,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            DEFAULT_CONSTANTS.COST_PER_BYTE,
        )

        # HONEST ABSORB
        time = CoinTimestamp(10000030, 2)
        # create the farming reward
        p2_singleton_puz: Program = create_p2_singleton_puzzle(
            SINGLETON_MOD_HASH,
            launcher_id,
            DELAY_TIME,
            DELAY_PH,
        )
        p2_singleton_ph: bytes32 = p2_singleton_puz.get_tree_hash()
        assert uncurry_pool_waitingroom_inner_puzzle(pool_wr_innerpuz) == (
            starting_ph,
            relative_lock_height,
            pk,
            p2_singleton_ph,
        )
        assert launcher_id_to_p2_puzzle_hash(launcher_id, DELAY_TIME, DELAY_PH) == p2_singleton_ph
        assert get_seconds_and_delayed_puzhash_from_p2_singleton_puzzle(p2_singleton_puz) == (DELAY_TIME, DELAY_PH)
        coin_db.farm_coin(p2_singleton_ph, time, 1750000000000)
        coin_sols: List[CoinSpend] = create_absorb_spend(
            launcher_coinsol,
            pool_state,
            launcher_coin,
            2,
            GENESIS_CHALLENGE,
            DELAY_TIME,
            DELAY_PH,  # height
        )
        # Spend it!
        coin_db.update_coin_store_for_spend_bundle(
            SpendBundle(coin_sols, G2Element()),
            time,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            DEFAULT_CONSTANTS.COST_PER_BYTE,
        )

        # ABSORB A NON EXISTENT REWARD (Negative test)
        last_coinsol: CoinSpend = list(
            filter(
                lambda e: e.coin.amount == START_AMOUNT,
                coin_sols,
            )
        )[0]
        coin_sols: List[CoinSpend] = create_absorb_spend(
            last_coinsol,
            pool_state,
            launcher_coin,
            2,
            GENESIS_CHALLENGE,
            DELAY_TIME,
            DELAY_PH,  # height
        )
        # filter for only the singleton solution
        singleton_coinsol: CoinSpend = list(
            filter(
                lambda e: e.coin.amount == START_AMOUNT,
                coin_sols,
            )
        )[0]
        # Spend it and hope it fails!
        try:
            coin_db.update_coin_store_for_spend_bundle(
                SpendBundle([singleton_coinsol], G2Element()),
                time,
                DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
                DEFAULT_CONSTANTS.COST_PER_BYTE,
            )
        except BadSpendBundleError as e:
            assert str(e) == "condition validation failure Err.ASSERT_ANNOUNCE_CONSUMED_FAILED"

        # SPEND A NON-REWARD P2_SINGLETON (Negative test)
        # create the dummy coin
        non_reward_p2_singleton = Coin(
            bytes32(32 * b"3"),
            p2_singleton_ph,
            uint64(1337),
        )
        coin_db._add_coin_entry(non_reward_p2_singleton, time)
        # construct coin solution for the p2_singleton coin
        bad_coinsol = CoinSpend(
            non_reward_p2_singleton,
            p2_singleton_puz,
            Program.to(
                [
                    pooling_innerpuz.get_tree_hash(),
                    non_reward_p2_singleton.name(),
                ]
            ),
        )
        # Spend it and hope it fails!
        try:
            coin_db.update_coin_store_for_spend_bundle(
                SpendBundle([singleton_coinsol, bad_coinsol], G2Element()),
                time,
                DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
                DEFAULT_CONSTANTS.COST_PER_BYTE,
            )
        except BadSpendBundleError as e:
            assert str(e) == "condition validation failure Err.ASSERT_ANNOUNCE_CONSUMED_FAILED"

        # ENTER WAITING ROOM
        # find the singleton
        singleton = get_most_recent_singleton_coin_from_coin_spend(last_coinsol)
        # get the relevant coin solution
        travel_coinsol, _ = create_travel_spend(
            last_coinsol,
            launcher_coin,
            pool_state,
            target_pool_state,
            GENESIS_CHALLENGE,
            DELAY_TIME,
            DELAY_PH,
        )
        # Test that we can retrieve the extra data
        assert solution_to_pool_state(travel_coinsol) == target_pool_state
        # sign the serialized state
        data = Program.to(bytes(target_pool_state)).get_tree_hash()
        sig: G2Element = AugSchemeMPL.sign(
            sk,
            (data + singleton.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA),
        )
        # Spend it!
        coin_db.update_coin_store_for_spend_bundle(
            SpendBundle([travel_coinsol], sig),
            time,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            DEFAULT_CONSTANTS.COST_PER_BYTE,
        )

        # ESCAPE TOO FAST (Negative test)
        # find the singleton
        singleton = get_most_recent_singleton_coin_from_coin_spend(travel_coinsol)
        # get the relevant coin solution
        return_coinsol, _ = create_travel_spend(
            travel_coinsol,
            launcher_coin,
            target_pool_state,
            pool_state,
            GENESIS_CHALLENGE,
            DELAY_TIME,
            DELAY_PH,
        )
        # sign the serialized target state
        sig = AugSchemeMPL.sign(
            sk,
            (data + singleton.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA),
        )
        # Spend it and hope it fails!
        try:
            coin_db.update_coin_store_for_spend_bundle(
                SpendBundle([return_coinsol], sig),
                time,
                DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
                DEFAULT_CONSTANTS.COST_PER_BYTE,
            )
        except BadSpendBundleError as e:
            assert str(e) == "condition validation failure Err.ASSERT_HEIGHT_RELATIVE_FAILED"

        # ABSORB WHILE IN WAITING ROOM
        time = CoinTimestamp(10000060, 3)
        # create the farming reward
        coin_db.farm_coin(p2_singleton_ph, time, 1750000000000)
        # generate relevant coin solutions
        coin_sols: List[CoinSpend] = create_absorb_spend(
            travel_coinsol,
            target_pool_state,
            launcher_coin,
            3,
            GENESIS_CHALLENGE,
            DELAY_TIME,
            DELAY_PH,  # height
        )
        # Spend it!
        coin_db.update_coin_store_for_spend_bundle(
            SpendBundle(coin_sols, G2Element()),
            time,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            DEFAULT_CONSTANTS.COST_PER_BYTE,
        )

        # LEAVE THE WAITING ROOM
        time = CoinTimestamp(20000000, 10000)
        # find the singleton
        singleton_coinsol: CoinSpend = list(
            filter(
                lambda e: e.coin.amount == START_AMOUNT,
                coin_sols,
            )
        )[0]
        singleton: Coin = get_most_recent_singleton_coin_from_coin_spend(singleton_coinsol)
        # get the relevant coin solution
        return_coinsol, _ = create_travel_spend(
            singleton_coinsol,
            launcher_coin,
            target_pool_state,
            pool_state,
            GENESIS_CHALLENGE,
            DELAY_TIME,
            DELAY_PH,
        )
        # Test that we can retrieve the extra data
        assert solution_to_pool_state(return_coinsol) == pool_state
        # sign the serialized target state
        data = Program.to([pooling_innerpuz.get_tree_hash(), START_AMOUNT, bytes(pool_state)]).get_tree_hash()
        sig: G2Element = AugSchemeMPL.sign(
            sk,
            (data + singleton.name() + DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA),
        )
        # Spend it!
        coin_db.update_coin_store_for_spend_bundle(
            SpendBundle([return_coinsol], sig),
            time,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            DEFAULT_CONSTANTS.COST_PER_BYTE,
        )

        # ABSORB ONCE MORE FOR GOOD MEASURE
        time = CoinTimestamp(20000000, 10005)
        # create the farming  reward
        coin_db.farm_coin(p2_singleton_ph, time, 1750000000000)
        coin_sols: List[CoinSpend] = create_absorb_spend(
            return_coinsol,
            pool_state,
            launcher_coin,
            10005,
            GENESIS_CHALLENGE,
            DELAY_TIME,
            DELAY_PH,  # height
        )
        # Spend it!
        coin_db.update_coin_store_for_spend_bundle(
            SpendBundle(coin_sols, G2Element()),
            time,
            DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
            DEFAULT_CONSTANTS.COST_PER_BYTE,
        )
