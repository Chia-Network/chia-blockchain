from typing import Tuple

from clvm import KEYWORD_FROM_ATOM

from clvm_tools.binutils import disassemble as bu_disassemble
from blspy import AugSchemeMPL
from src.types.blockchain_format.coin import Coin
from src.types.condition_opcodes import ConditionOpcode
from src.types.blockchain_format.program import Program
from src.types.blockchain_format.sized_bytes import bytes32
from src.types.spend_bundle import SpendBundle
from src.util.condition_tools import conditions_dict_for_solution
from src.util.condition_tools import pkm_pairs_for_conditions_dict


CONDITIONS = dict((k, bytes(v)[0]) for k, v in ConditionOpcode.__members__.items())
KFA = {v: k for k, v in CONDITIONS.items()}


# information needed to spend a cc
# if we ever support more genesis conditions, like a re-issuable coin,
# we may need also to save the `genesis_coin_mod` or its hash


def disassemble(sexp):
    """
    This version of `disassemble` also disassembles condition opcodes like `ASSERT_ANNOUNCEMENT_CONSUMED`.
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

    pks = []
    msgs = []

    print("=" * 80)
    for coin_solution in spend_bundle.coin_solutions:
        coin = coin_solution.coin
        puzzle_reveal = coin_solution.puzzle_reveal
        solution = coin_solution.solution

        print(f"consuming coin {dump_coin(coin)}")
        print(f"  with id {coin.name()}")
        print()
        print(f"\nbrun -y main.sym '{bu_disassemble(puzzle_reveal)}' '{bu_disassemble(solution)}'")
        error, conditions, cost = conditions_dict_for_solution(puzzle_reveal, solution)
        if error:
            print(f"*** error {error}")
        elif conditions is not None:
            for pk, m in pkm_pairs_for_conditions_dict(conditions, coin.name()):
                pks.append(pk)
                msgs.append(m)
            print()
            r = puzzle_reveal.run(solution)
            print(disassemble(r))
            print()
            if conditions and len(conditions) > 0:
                print("grouped conditions:")
                for condition_programs in conditions.values():
                    print()
                    for c in condition_programs:
                        if len(c.vars) == 1:
                            as_prog = Program.to([c.opcode, c.vars[0]])
                        if len(c.vars) == 2:
                            as_prog = Program.to([c.opcode, c.vars[0], c.vars[1]])
                        print(f"  {disassemble(as_prog)}")
                print()
            else:
                print("(no output conditions generated)")
        print()
        print("-------")

    created = set(spend_bundle.additions())
    spent = set(spend_bundle.removals())

    zero_coin_set = set(coin.name() for coin in created if coin.amount == 0)

    ephemeral = created.intersection(spent)
    created.difference_update(ephemeral)
    spent.difference_update(ephemeral)
    print()
    print("spent coins")
    for coin in sorted(spent, key=lambda _: _.name()):
        print(f"  {dump_coin(coin)}")
        print(f"      => spent coin id {coin.name()}")
    print()
    print("created coins")
    for coin in sorted(created, key=lambda _: _.name()):
        print(f"  {dump_coin(coin)}")
        print(f"      => created coin id {coin.name()}")

    if ephemeral:
        print()
        print("ephemeral coins")
        for coin in sorted(ephemeral, key=lambda _: _.name()):
            print(f"  {dump_coin(coin)}")
            print(f"      => created coin id {coin.name()}")

    print()
    print()
    print(f"zero_coin_set = {sorted(zero_coin_set)}")
    print()
    print(f"created announcements = {spend_bundle.announcements()}")
    print()
    print()
    print("=" * 80)
    print()
    if len(msgs) > 0:
        validates = AugSchemeMPL.aggregate_verify(pks, msgs, spend_bundle.aggregated_signature)
        print(f"aggregated signature check pass: {validates}")


def solution_for_pay_to_any(puzzle_hash_amount_pairs: Tuple[bytes32, int]) -> Program:
    output_conditions = [
        [ConditionOpcode.CREATE_COIN, puzzle_hash, amount] for puzzle_hash, amount in puzzle_hash_amount_pairs
    ]
    return Program.to(output_conditions)
