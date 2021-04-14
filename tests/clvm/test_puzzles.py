# flake8: noqa: F811, F401
import asyncio
import logging
from typing import Iterable, List, Tuple

import pytest
from blspy import AugSchemeMPL, BasicSchemeMPL, G1Element, G2Element
from clvm.casts import int_to_bytes
from clvm_tools import binutils

from chia.consensus.blockchain import ReceiveBlockResult, Blockchain
from chia.consensus.cost_calculator import calculate_cost_of_program
from chia.full_node.mempool_manager import MempoolManager
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_solution import CoinSolution
from chia.types.condition_with_args import ConditionWithArgs
from chia.types.full_block import FullBlock
from chia.types.mempool_inclusion_status import MempoolInclusionStatus
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import ConditionOpcode
from chia.util.hash import std_hash
from chia.util.ints import uint32
from chia.wallet.puzzles import (
    p2_conditions,
    p2_delegated_conditions,
    p2_delegated_puzzle,
    p2_delegated_puzzle_or_hidden_puzzle,
    p2_m_of_n_delegate_direct,
    p2_puzzle_hash,
)
from tests.util.key_tool import KeyTool
from tests.core.fixtures import empty_blockchain  # noqa: F401
from tests.setup_nodes import bt

from ..core.make_block_generator import int_to_public_key

log = logging.getLogger(__name__)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


def secret_exponent_for_index(index: int) -> int:
    blob = index.to_bytes(32, "big")
    hashed_blob = BasicSchemeMPL.key_gen(std_hash(b"foo" + blob))
    r = int.from_bytes(hashed_blob, "big")
    return r


def public_key_for_index(index: int, key_lookup: KeyTool) -> G1Element:
    secret_exponent = secret_exponent_for_index(index)
    key_lookup.add_secret_exponents([secret_exponent])
    return int_to_public_key(secret_exponent)


def throwaway_puzzle_hash(index: int, key_lookup: KeyTool) -> bytes32:
    return p2_delegated_puzzle.puzzle_for_pk(bytes(public_key_for_index(index, key_lookup))).get_tree_hash()


async def do_test_spend(
    blockchain: Blockchain,
    puzzle_reveal: Program,
    solution: Program,
    payments: Iterable[Tuple[bytes32, int]],
    key_lookup: KeyTool,
    expected_conditions: List[ConditionWithArgs],
    skip_mempool_check=False,
) -> None:
    """
    This method will farm a coin paid to the hash of `puzzle_reveal`, then try to spend it
    with `solution`, and verify that the created coins correspond to `payments`.

    The `key_lookup` is used to create a signed version of the `SpendBundle`, although at
    this time, signatures are not verified.
    """
    peak = blockchain.get_peak()
    if peak is not None:
        blocks: List[FullBlock] = await blockchain.block_store.get_full_blocks_at(
            [uint32(h) for h in range(0, peak.height + 1)]
        )
    else:
        blocks = []
    puzzle_hash: bytes32 = puzzle_reveal.get_tree_hash()

    # Adds some balance to this puzzle hash, so we can spend it
    blocks = bt.get_consecutive_blocks(
        3,
        blocks,
        farmer_reward_puzzle_hash=puzzle_hash,
        pool_reward_puzzle_hash=puzzle_hash,
        guarantee_transaction_block=True,
    )
    assert (await blockchain.receive_block(blocks[-3]))[0] == ReceiveBlockResult.NEW_PEAK
    assert (await blockchain.receive_block(blocks[-2]))[0] == ReceiveBlockResult.NEW_PEAK
    assert (await blockchain.receive_block(blocks[-1]))[0] == ReceiveBlockResult.NEW_PEAK

    # spend it
    coin_to_spend: Coin = list(blocks[-1].get_included_reward_coins())[0]
    coin_solution: CoinSolution = CoinSolution(coin_to_spend, puzzle_reveal, solution)

    unsigned_spend_bundle: SpendBundle = SpendBundle([coin_solution], G2Element())

    # make sure we can actually sign the solution
    signatures: List[G2Element] = []
    for coin_solution in unsigned_spend_bundle.coin_solutions:
        signature = key_lookup.signature_for_solution(coin_solution, blockchain.constants.AGG_SIG_ME_ADDITIONAL_DATA)
        signatures.append(signature)
    spend_bundle: SpendBundle = SpendBundle(unsigned_spend_bundle.coin_solutions, AugSchemeMPL.aggregate(signatures))

    # Make sure the spend bundle can be included in the mempool
    if not skip_mempool_check:
        mempool_manager: MempoolManager = MempoolManager(blockchain.coin_store, blockchain.constants)
        await mempool_manager.new_peak(blockchain.get_peak())
        cost_result = await mempool_manager.pre_validate_spendbundle(spend_bundle)
        assert cost_result.error is None
        res = await mempool_manager.add_spendbundle(spend_bundle, cost_result, spend_bundle.name())
        assert res[1] == MempoolInclusionStatus.SUCCESS

    # Spend the spend bundle and add the block where it's spent
    blocks = bt.get_consecutive_blocks(1, blocks, guarantee_transaction_block=True, transaction_data=spend_bundle)
    result = await blockchain.receive_block(blocks[-1])
    assert result[1] is None
    assert result[0] == ReceiveBlockResult.NEW_PEAK

    # ensure all outputs are there
    for puzzle_hash, amount in payments:
        records: List[CoinRecord] = await blockchain.coin_store.get_coin_records_by_puzzle_hash(False, puzzle_hash)
        assert len(records) > 0
        assert amount in [rec.coin.amount for rec in records]

    generator = blocks[-1].transactions_generator
    assert generator is not None
    cost_result = calculate_cost_of_program(generator, blockchain.constants.CLVM_COST_RATIO_CONSTANT)
    conditions_set = set(
        [
            condition.get_hash()
            for npc in cost_result.npc_list
            for condition_type in npc.conditions
            for condition in condition_type[1]
        ]
    )
    assert set(c.get_hash() for c in expected_conditions) == conditions_set


def default_payments_and_conditions(
    initial_index: int, key_lookup: KeyTool
) -> Tuple[List[Tuple[bytes32, int]], Program, List[ConditionWithArgs]]:

    payments = [
        (throwaway_puzzle_hash(initial_index + 1, key_lookup), initial_index * 1000),
        (throwaway_puzzle_hash(initial_index + 2, key_lookup), (initial_index + 1) * 1000),
    ]
    conditions = Program.to([make_create_coin_condition(ph, amount) for ph, amount in payments])
    conditions_with_args = [
        ConditionWithArgs(ConditionOpcode(cond.first().as_atom()), cond.rest().as_atom_list())
        for cond in conditions.as_iter()
    ]
    return payments, conditions, conditions_with_args


def make_create_coin_condition(puzzle_hash, amount):
    return Program.to([ConditionOpcode.CREATE_COIN, puzzle_hash, amount])


class TestPuzzles:
    @pytest.mark.asyncio
    async def test_p2_conditions(self, empty_blockchain):
        key_lookup = KeyTool()
        payments, conditions, cwa = default_payments_and_conditions(1, key_lookup)

        puzzle = p2_conditions.puzzle_for_conditions(conditions)
        solution = p2_conditions.solution_for_conditions(conditions)

        await do_test_spend(empty_blockchain, puzzle, solution, payments, key_lookup, cwa)

    @pytest.mark.asyncio
    async def test_p2_delegated_conditions(self, empty_blockchain):
        key_lookup = KeyTool()
        payments, conditions, cwa = default_payments_and_conditions(1, key_lookup)

        pk = public_key_for_index(1, key_lookup)

        puzzle = p2_delegated_conditions.puzzle_for_pk(pk)
        solution = p2_delegated_conditions.solution_for_conditions(conditions)
        with pytest.raises(AssertionError):
            # Test do do_not_spend code to make sure its checking conditions
            await do_test_spend(empty_blockchain, puzzle, solution, payments, key_lookup, cwa)

        cwa.append(ConditionWithArgs(ConditionOpcode.AGG_SIG, [bytes(pk), conditions.get_tree_hash()]))
        await do_test_spend(empty_blockchain, puzzle, solution, payments, key_lookup, cwa)

    @pytest.mark.asyncio
    async def test_p2_delegated_puzzle_simple(self, empty_blockchain):
        key_lookup = KeyTool()
        payments, conditions, cwa = default_payments_and_conditions(1, key_lookup)

        pk = public_key_for_index(1, key_lookup)

        puzzle = p2_delegated_puzzle.puzzle_for_pk(pk)
        delegated_puzzle = p2_conditions.puzzle_for_conditions(conditions)
        solution = p2_delegated_puzzle.solution_for_conditions(conditions)
        cwa.append(ConditionWithArgs(ConditionOpcode.AGG_SIG_ME, [bytes(pk), delegated_puzzle.get_tree_hash()]))

        await do_test_spend(empty_blockchain, puzzle, solution, payments, key_lookup, cwa)

    @pytest.mark.asyncio
    async def test_p2_delegated_puzzle_graftroot(self, empty_blockchain):
        key_lookup = KeyTool()
        payments, conditions, cwa = default_payments_and_conditions(1, key_lookup)

        original_pk = public_key_for_index(1, key_lookup)
        delegated_pk = public_key_for_index(8, key_lookup)
        delegated_puzzle = p2_delegated_conditions.puzzle_for_pk(delegated_pk)
        delegated_solution = p2_delegated_conditions.solution_for_conditions(conditions)

        puzzle_program = p2_delegated_puzzle.puzzle_for_pk(original_pk)
        solution = p2_delegated_puzzle.solution_for_delegated_puzzle(delegated_puzzle, delegated_solution)
        cwa.append(
            ConditionWithArgs(ConditionOpcode.AGG_SIG_ME, [bytes(original_pk), delegated_puzzle.get_tree_hash()])
        )
        cwa.append(ConditionWithArgs(ConditionOpcode.AGG_SIG, [bytes(delegated_pk), conditions.get_tree_hash()]))

        await do_test_spend(empty_blockchain, puzzle_program, solution, payments, key_lookup, cwa)

    @pytest.mark.asyncio
    async def test_p2_puzzle_hash(self, empty_blockchain):
        key_lookup = KeyTool()
        payments, conditions, cwa = default_payments_and_conditions(1, key_lookup)

        inner_pk = public_key_for_index(4, key_lookup)
        inner_puzzle = p2_delegated_conditions.puzzle_for_pk(inner_pk)
        inner_solution = p2_delegated_conditions.solution_for_conditions(conditions)
        inner_puzzle_hash = inner_puzzle.get_tree_hash()

        puzzle_program = p2_puzzle_hash.puzzle_for_inner_puzzle_hash(inner_puzzle_hash)
        assert puzzle_program == p2_puzzle_hash.puzzle_for_inner_puzzle(inner_puzzle)
        solution = p2_puzzle_hash.solution_for_inner_puzzle_and_inner_solution(inner_puzzle, inner_solution)

        cwa.append(ConditionWithArgs(ConditionOpcode.AGG_SIG, [bytes(inner_pk), conditions.get_tree_hash()]))

        await do_test_spend(empty_blockchain, puzzle_program, solution, payments, key_lookup, cwa)

    @pytest.mark.asyncio
    async def test_p2_m_of_n_delegated_puzzle(self, empty_blockchain):
        key_lookup = KeyTool()
        payments, conditions, cwa = default_payments_and_conditions(1, key_lookup)

        pks = [public_key_for_index(_, key_lookup) for _ in range(1, 6)]
        m = 3

        delegated_puzzle = p2_conditions.puzzle_for_conditions(conditions)
        delegated_solution = []

        puzzle_program = p2_m_of_n_delegate_direct.puzzle_for_m_of_public_key_list(m, pks)
        selectors = [1, [], [], 1, 1]
        solution = p2_m_of_n_delegate_direct.solution_for_delegated_puzzle(
            m, selectors, delegated_puzzle, delegated_solution
        )
        for n, pk in enumerate(pks):
            if selectors[n] == 1:
                cwa.append(ConditionWithArgs(ConditionOpcode.AGG_SIG, [bytes(pk), delegated_puzzle.get_tree_hash()]))

        await do_test_spend(empty_blockchain, puzzle_program, solution, payments, key_lookup, cwa)

    @pytest.mark.asyncio
    async def test_p2_delegated_puzzle_or_hidden_puzzle_with_hidden_puzzle(self, empty_blockchain):
        key_lookup = KeyTool()
        payments, conditions, cwa = default_payments_and_conditions(1, key_lookup)

        hidden_puzzle = p2_conditions.puzzle_for_conditions(conditions)
        hidden_public_key = public_key_for_index(10, key_lookup)

        puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_public_key_and_hidden_puzzle(
            hidden_public_key, hidden_puzzle
        )
        solution = p2_delegated_puzzle_or_hidden_puzzle.solution_for_hidden_puzzle(
            hidden_public_key, hidden_puzzle, Program.to(0)
        )

        await do_test_spend(empty_blockchain, puzzle, solution, payments, key_lookup, cwa)

    @pytest.mark.asyncio
    async def test_p2_delegated_puzzle_or_hidden_puzzle_with_hidden_puzzle_recursive(self, empty_blockchain):
        """
        Spends a hidden puzzle, where the hidden puzzle is the same puzzle but with a different pk and spent using
        the delegated method, not hidden.
        """
        key_lookup = KeyTool()
        payments, conditions, cwa = default_payments_and_conditions(1, key_lookup)

        inner_pk = public_key_for_index(4, key_lookup)
        inner_delegated_puzzle = p2_conditions.puzzle_for_conditions(conditions)
        inner_delegated_solution = Program.to(binutils.assemble("()"))
        inner_synthetic_public_key = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_public_key(
            inner_pk, p2_delegated_puzzle_or_hidden_puzzle.DEFAULT_HIDDEN_PUZZLE.get_tree_hash()
        )
        inner_synthetic_offset = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_offset(
            inner_pk, p2_delegated_puzzle_or_hidden_puzzle.DEFAULT_HIDDEN_PUZZLE.get_tree_hash()
        )
        inner_secret_exponent = key_lookup.get(bytes(inner_pk))
        assert inner_synthetic_public_key == int_to_public_key(inner_synthetic_offset) + inner_pk
        assert int_to_public_key(inner_secret_exponent) == inner_pk
        inner_synthetic_secret_exponent = inner_secret_exponent + inner_synthetic_offset
        key_lookup.add_secret_exponents([inner_synthetic_secret_exponent])

        cwa.append(
            ConditionWithArgs(
                ConditionOpcode.AGG_SIG_ME, [bytes(inner_synthetic_public_key), inner_delegated_puzzle.get_tree_hash()]
            )
        )

        for ph, amount in payments:
            # All the payees and amounts are in the payload that is signed
            assert ph in bytes(inner_delegated_puzzle)
            assert int_to_bytes(amount) in bytes(inner_delegated_puzzle)

        hidden_puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_pk(inner_pk)
        hidden_solution = p2_delegated_puzzle_or_hidden_puzzle.solution_for_delegated_puzzle(
            inner_delegated_puzzle, inner_delegated_solution
        )
        hidden_public_key = public_key_for_index(10, key_lookup)

        puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_public_key_and_hidden_puzzle(
            hidden_public_key, hidden_puzzle
        )
        solution = p2_delegated_puzzle_or_hidden_puzzle.solution_for_hidden_puzzle(
            hidden_public_key, hidden_puzzle, hidden_solution
        )

        await do_test_spend(empty_blockchain, puzzle, solution, payments, key_lookup, cwa)

    @pytest.mark.asyncio
    async def test_p2_delegated_puzzle_or_hidden_puzzle_with_default_hidden_puzzle_fails(self, empty_blockchain):
        key_lookup = KeyTool()
        payments, conditions, cwa = default_payments_and_conditions(1, key_lookup)

        hidden_puzzle = p2_delegated_puzzle_or_hidden_puzzle.DEFAULT_HIDDEN_PUZZLE
        hidden_public_key = public_key_for_index(10, key_lookup)

        puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_public_key_and_hidden_puzzle(
            hidden_public_key, hidden_puzzle
        )
        solution = p2_delegated_puzzle_or_hidden_puzzle.solution_for_hidden_puzzle(
            hidden_public_key, hidden_puzzle, Program.to(0)
        )
        # Test rejection in mempool validation
        try:
            await do_test_spend(empty_blockchain, puzzle, solution, payments, key_lookup, cwa)
            assert False
        except Exception as e:
            assert "EvalError: = takes exactly 2 arguments" in str(e)

        # Test rejection in block creation
        try:
            await do_test_spend(empty_blockchain, puzzle, solution, payments, key_lookup, cwa, True)
            assert False
        except Exception as e:
            assert "EvalError: = takes exactly 2 arguments" in str(e)

    async def do_test_spend_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle(
        self, blockchain, hidden_pub_key_index, hidden_puzzle=None
    ):
        key_lookup = KeyTool()
        payments, conditions, _ = default_payments_and_conditions(1, key_lookup)

        if hidden_puzzle is None:
            hidden_puzzle = p2_conditions.puzzle_for_conditions(conditions)
        hidden_public_key = public_key_for_index(hidden_pub_key_index, key_lookup)

        puzzle = p2_delegated_puzzle_or_hidden_puzzle.puzzle_for_public_key_and_hidden_puzzle(
            hidden_public_key, hidden_puzzle
        )
        payable_payments, payable_conditions, cwa = default_payments_and_conditions(5, key_lookup)

        delegated_puzzle = p2_conditions.puzzle_for_conditions(payable_conditions)
        delegated_solution = Program.to(binutils.assemble("()"))

        synthetic_public_key = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_public_key(
            hidden_public_key, hidden_puzzle.get_tree_hash()
        )

        solution = p2_delegated_puzzle_or_hidden_puzzle.solution_for_delegated_puzzle(
            delegated_puzzle, delegated_solution
        )

        hidden_puzzle_hash = hidden_puzzle.get_tree_hash()
        synthetic_offset = p2_delegated_puzzle_or_hidden_puzzle.calculate_synthetic_offset(
            hidden_public_key, hidden_puzzle_hash
        )

        assert synthetic_public_key == int_to_public_key(synthetic_offset) + hidden_public_key

        secret_exponent = key_lookup.get(bytes(hidden_public_key))
        assert int_to_public_key(secret_exponent) == hidden_public_key

        synthetic_secret_exponent = secret_exponent + synthetic_offset
        key_lookup.add_secret_exponents([synthetic_secret_exponent])
        cwa.append(
            ConditionWithArgs(
                ConditionOpcode.AGG_SIG_ME, [bytes(synthetic_public_key), delegated_puzzle.get_tree_hash()]
            )
        )
        for ph, amount in payable_payments:
            # All the payees and amounts are in the payload that is signed
            assert ph in bytes(delegated_puzzle)
            assert int_to_bytes(amount) in bytes(delegated_puzzle)

        await do_test_spend(blockchain, puzzle, solution, payable_payments, key_lookup, cwa)

    @pytest.mark.asyncio
    async def test_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle(self, empty_blockchain):
        for hidden_pub_key_index in range(1, 10):
            await self.do_test_spend_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle(
                empty_blockchain, hidden_pub_key_index
            )

    @pytest.mark.asyncio
    async def test_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle_default_hidden(self, empty_blockchain):
        hidden_puzzle = p2_delegated_puzzle_or_hidden_puzzle.DEFAULT_HIDDEN_PUZZLE
        for hidden_pub_key_index in range(1, 10):
            await self.do_test_spend_p2_delegated_puzzle_or_hidden_puzzle_with_delegated_puzzle(
                empty_blockchain, hidden_pub_key_index, hidden_puzzle
            )
