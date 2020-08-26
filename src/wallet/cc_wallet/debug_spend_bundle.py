from typing import Tuple

from clvm import KEYWORD_FROM_ATOM

from clvm_tools.binutils import disassemble as bu_disassemble

from stages.stage_0 import run_program

from src.types.coin import Coin
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.util.condition_tools import conditions_dict_for_solution


CONDITIONS = dict((k, bytes(v)[0]) for k, v in ConditionOpcode.__members__.items())
KFA = {v: k for k, v in CONDITIONS.items()}


# information needed to spend a cc
# if we ever support more genesis conditions, like a re-issuable coin,
# we may need also to save the `genesis_coin_mod` or its hash


def disassemble(sexp):
    """
    This version of `disassemble` also disassembles condition opcodes like `ASSERT_COIN_CONSUMED`.
    """
    kfa = dict(KEYWORD_FROM_ATOM)
    kfa.update((Program.to(k).as_atom(), v) for k, v in KFA.items())
    return bu_disassemble(sexp, kfa)


def coin_as_program(coin: Coin) -> Program:
    """
    Convenience function for when putting `coin_info` into a solution.
    """
    return Program.to([coin.parent_coin_info, coin.puzzle_hash, coin.amount])


def dump_coin(coin: Coin) -> str:
    return disassemble(coin_as_program(coin))


def debug_spend_bundle(spend_bundle: SpendBundle) -> None:
    """
    Print a lot of useful information about a `SpendBundle` that might help with debugging
    its clvm.
    """

    assert_consumed_set = set()

    print("=" * 80)
    for coin_solution in spend_bundle.coin_solutions:
        coin, solution_pair = coin_solution.coin, coin_solution.solution
        puzzle_reveal = solution_pair.first()
        solution = solution_pair.rest().first()

        print(f"consuming coin {dump_coin(coin)}")
        print(f"  with id {coin.name()}")
        print()
        print(
            f"\nbrun -y main.sym '{bu_disassemble(puzzle_reveal)}' '{bu_disassemble(solution)}'"
        )
        error, conditions, cost = conditions_dict_for_solution(
            Program.to([puzzle_reveal, solution])
        )
        if error:
            print(f"*** error {error}")
        else:
            print()
            cost, r = run_program(puzzle_reveal, solution)
            print(disassemble(r))
            print()
            if conditions and len(conditions) > 0:
                print("grouped conditions:")
                for condition_programs in conditions.values():
                    print()
                    for c in condition_programs:
                        as_prog = Program.to([c.opcode, c.var1, c.var2])
                        print(f"  {disassemble(as_prog)}")
                print()
                for _ in conditions.get(ConditionOpcode.ASSERT_COIN_CONSUMED, []):
                    assert_consumed_set.add(bytes32(_.var1))
            else:
                print("(no output conditions generated)")
        print()
        print("-------")

    additions = spend_bundle.additions()
    removals = spend_bundle.removals()
    print()
    print("created coins")
    for coin in additions:
        print(f"  {dump_coin(coin)}")
        print(f"      => created coin id {coin.name()}")
    print()
    print("spent coins")
    for coin in removals:
        print(f"  {dump_coin(coin)}")
        print(f"      => spent coin id {coin.name()}")

    zero_coin_set = set()
    for coin in additions:
        if coin.amount == 0:
            zero_coin_set.add(coin.name())

    print()
    print(f"assert_consumed_set = {sorted(assert_consumed_set)}")
    print()
    print(f"zero_coin_set = {sorted(zero_coin_set)}")
    print()
    set_difference = zero_coin_set ^ assert_consumed_set
    print(f"zero_coin_set ^ assert_consumed_set = {sorted(set_difference)}")
    if len(set_difference):
        print("not all zero coins asserted consumed or vice versa, entering debugger")
        breakpoint()

    print()
    print("=" * 80)


def solution_for_pay_to_any(puzzle_hash_amount_pairs: Tuple[bytes32, int]) -> Program:
    output_conditions = [
        [ConditionOpcode.CREATE_COIN, puzzle_hash, amount]
        for puzzle_hash, amount in puzzle_hash_amount_pairs
    ]
    return Program.to(output_conditions)
