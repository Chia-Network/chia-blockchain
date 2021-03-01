from typing import Dict

import blspy

from src.full_node.bundle_tools import best_solution_program
from src.types.blockchain_format.coin import Coin
from src.types.blockchain_format.program import Program, SerializedProgram
from src.types.coin_solution import CoinSolution
from src.types.condition_opcodes import ConditionOpcode
from src.types.spend_bundle import SpendBundle
from src.util.ints import uint64
from src.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk, solution_for_conditions


def puzzle_hash_for_index(index: int, puzzle_hash_db: dict) -> bytes:
    public_key = bytes(blspy.G1Element.generator() * index)
    puzzle = puzzle_for_pk(public_key)
    puzzle_hash = puzzle.get_tree_hash()
    puzzle_hash_db[puzzle_hash] = puzzle
    return puzzle_hash


def make_fake_coin(index: int, puzzle_hash_db: dict) -> Coin:
    """
    Make a fake coin with parent id equal to the index (ie. a genesis block coin)

    """
    parent = index.to_bytes(32, "big")
    puzzle_hash = puzzle_hash_for_index(index, puzzle_hash_db)
    amount = 100000
    return Coin(parent, puzzle_hash, uint64(amount))


def conditions_for_payment(coin) -> Program:
    d: Dict = {}  # a throwaway db since we don't care
    new_puzzle_hash = puzzle_hash_for_index(int.from_bytes(coin.puzzle_hash, "big"), d)
    return Program.to([[ConditionOpcode.CREATE_COIN, new_puzzle_hash, coin.amount]])


def make_block_generator(count: int) -> SerializedProgram:
    puzzle_hash_db: Dict = dict()
    coins = [make_fake_coin(_, puzzle_hash_db) for _ in range(count)]

    coin_solutions = []
    for coin in coins:
        puzzle_reveal = puzzle_hash_db[coin.puzzle_hash]
        conditions = conditions_for_payment(coin)
        solution = solution_for_conditions(conditions)
        coin_solution = CoinSolution(coin, puzzle_reveal, solution)
        coin_solutions.append(coin_solution)

    spend_bundle = SpendBundle(coin_solutions, blspy.G2Element.infinity())
    return best_solution_program(spend_bundle)
