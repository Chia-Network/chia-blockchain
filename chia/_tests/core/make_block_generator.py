from __future__ import annotations

from typing import Dict

from chia_rs import G1Element, G2Element, PrivateKey

from chia.full_node.bundle_tools import simple_solution_generator
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions

GROUP_ORDER = 0x73EDA753299D7D483339D80809A1D80553BDA402FFFE5BFEFFFFFFFF00000001


def int_to_public_key(index: int) -> G1Element:
    index = index % GROUP_ORDER
    private_key_from_int = PrivateKey.from_bytes(index.to_bytes(32, "big"))
    return private_key_from_int.get_g1()


def puzzle_hash_for_index(index: int, puzzle_hash_db: Dict[bytes32, SerializedProgram]) -> bytes32:
    public_key: G1Element = int_to_public_key(index)
    puzzle = SerializedProgram.from_program(puzzle_for_pk(public_key))
    puzzle_hash: bytes32 = puzzle.get_tree_hash()
    puzzle_hash_db[puzzle_hash] = puzzle
    return puzzle_hash


def make_fake_coin(index: int, puzzle_hash_db: Dict[bytes32, SerializedProgram]) -> Coin:
    """
    Make a fake coin with parent id equal to the index (ie. a genesis block coin)

    """
    parent: bytes32 = bytes32(index.to_bytes(32, "big"))
    puzzle_hash: bytes32 = puzzle_hash_for_index(index, puzzle_hash_db)
    amount: uint64 = uint64(100000)
    return Coin(parent, puzzle_hash, amount)


def conditions_for_payment(coin: Coin) -> Program:
    d: Dict[bytes32, SerializedProgram] = {}  # a throwaway db since we don't care
    new_puzzle_hash = puzzle_hash_for_index(int.from_bytes(coin.puzzle_hash, "big"), d)
    ret: Program = Program.to([[ConditionOpcode.CREATE_COIN, new_puzzle_hash, coin.amount]])
    return ret


def make_spend_bundle(count: int) -> SpendBundle:
    puzzle_hash_db: Dict[bytes32, SerializedProgram] = {}
    coins = [make_fake_coin(_, puzzle_hash_db) for _ in range(count)]

    coin_spends = []
    for coin in coins:
        puzzle_reveal = puzzle_hash_db[coin.puzzle_hash]
        conditions = conditions_for_payment(coin)
        solution = SerializedProgram.from_program(solution_for_conditions(conditions))
        coin_spend = make_spend(coin, puzzle_reveal, solution)
        coin_spends.append(coin_spend)

    spend_bundle = SpendBundle(coin_spends, G2Element())
    return spend_bundle


def make_block_generator(count: int) -> BlockGenerator:
    spend_bundle = make_spend_bundle(count)
    return simple_solution_generator(spend_bundle)
