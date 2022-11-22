from __future__ import annotations

from typing import List

from blspy import AugSchemeMPL, G1Element
from clvm import KEYWORD_FROM_ATOM
from clvm_tools.binutils import disassemble as bu_disassemble

from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.hash import std_hash

CONDITIONS = dict((k, bytes(v)[0]) for k, v in ConditionOpcode.__members__.items())  # pylint: disable=E1101
KFA = {v: k for k, v in CONDITIONS.items()}


# information needed to spend a cc
# if we ever support more genesis conditions, like a re-issuable coin,
# we may need also to save the `genesis_coin_mod` or its hash


def disassemble(sexp: Program):
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


def debug_spend_bundle(spend_bundle, agg_sig_additional_data=DEFAULT_CONSTANTS.AGG_SIG_ME_ADDITIONAL_DATA) -> None:
    """
    Print a lot of useful information about a `SpendBundle` that might help with debugging
    its clvm.
    """

    pks = []
    msgs = []

    created_coin_announcements: List[List[bytes]] = []
    asserted_coin_announcements = []
    created_puzzle_announcements: List[List[bytes]] = []
    asserted_puzzle_announcements = []

    print("=" * 80)
    for coin_spend in spend_bundle.coin_spends:
        coin = coin_spend.coin
        puzzle_reveal = Program.from_bytes(bytes(coin_spend.puzzle_reveal))
        solution = Program.from_bytes(bytes(coin_spend.solution))
        coin_name = coin.name()

        if puzzle_reveal.get_tree_hash() != coin_spend.coin.puzzle_hash:
            print("*** BAD PUZZLE REVEAL")
            print(f"{puzzle_reveal.get_tree_hash().hex()} vs {coin_spend.coin.puzzle_hash.hex()}")
            print("*" * 80)
            continue

        print(f"consuming coin {dump_coin(coin)}")
        print(f"  with id {coin_name.hex()}")
        print()
        print(f"\nbrun -y main.sym '{bu_disassemble(puzzle_reveal)}' '{bu_disassemble(solution)}'")
        error, conditions, cost = conditions_dict_for_solution(puzzle_reveal, solution, INFINITE_COST)
        if error:
            print(f"*** error {error}")
        elif conditions is not None:
            for pk_bytes, m in pkm_pairs_for_conditions_dict(conditions, coin_name, agg_sig_additional_data):
                pks.append(G1Element.from_bytes(pk_bytes))
                msgs.append(m)
            print()
            cost, r = puzzle_reveal.run_with_cost(INFINITE_COST, solution)  # type: ignore
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
                created_coin_announcements.extend(
                    [coin_name] + _.vars for _ in conditions.get(ConditionOpcode.CREATE_COIN_ANNOUNCEMENT, [])
                )
                asserted_coin_announcements.extend(
                    [_.vars[0].hex() for _ in conditions.get(ConditionOpcode.ASSERT_COIN_ANNOUNCEMENT, [])]
                )
                created_puzzle_announcements.extend(
                    [puzzle_reveal.get_tree_hash()] + _.vars
                    for _ in conditions.get(ConditionOpcode.CREATE_PUZZLE_ANNOUNCEMENT, [])
                )
                asserted_puzzle_announcements.extend(
                    [_.vars[0].hex() for _ in conditions.get(ConditionOpcode.ASSERT_PUZZLE_ANNOUNCEMENT, [])]
                )
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
        print(f"      => spent coin id {coin.name().hex()}")
    print()
    print("created coins")
    for coin in sorted(created, key=lambda _: _.name()):
        print(f"  {dump_coin(coin)}")
        print(f"      => created coin id {coin.name().hex()}")

    if ephemeral:
        print()
        print("ephemeral coins")
        for coin in sorted(ephemeral, key=lambda _: _.name()):
            print(f"  {dump_coin(coin)}")
            print(f"      => created coin id {coin.name().hex()}")

    created_coin_announcement_pairs = [(_, std_hash(b"".join(_)).hex()) for _ in created_coin_announcements]
    if created_coin_announcement_pairs:
        print("created coin announcements")
        for announcement, hashed in sorted(created_coin_announcement_pairs, key=lambda _: _[-1]):
            as_hex = [f"0x{_.hex()}" for _ in announcement]
            print(f"  {as_hex} =>\n      {hashed}")

    eor_coin_announcements = sorted(
        set(_[-1] for _ in created_coin_announcement_pairs) ^ set(asserted_coin_announcements)
    )

    created_puzzle_announcement_pairs = [(_, std_hash(b"".join(_)).hex()) for _ in created_puzzle_announcements]
    if created_puzzle_announcements:
        print("created puzzle announcements")
        for announcement, hashed in sorted(created_puzzle_announcement_pairs, key=lambda _: _[-1]):
            as_hex = [f"0x{_.hex()}" for _ in announcement]
            print(f"  {as_hex} =>\n      {hashed}")

    eor_puzzle_announcements = sorted(
        set(_[-1] for _ in created_puzzle_announcement_pairs) ^ set(asserted_puzzle_announcements)
    )

    print()
    print()
    print(f"zero_coin_set = {sorted(zero_coin_set)}")
    print()
    if created_coin_announcement_pairs or asserted_coin_announcements:
        print(f"created  coin announcements = {sorted([_[-1] for _ in created_coin_announcement_pairs])}")
        print()
        print(f"asserted coin announcements = {sorted(asserted_coin_announcements)}")
        print()
        print(f"symdiff of coin announcements = {sorted(eor_coin_announcements)}")
        print()
    if created_puzzle_announcement_pairs or asserted_puzzle_announcements:
        print(f"created  puzzle announcements = {sorted([_[-1] for _ in created_puzzle_announcement_pairs])}")
        print()
        print(f"asserted puzzle announcements = {sorted(asserted_puzzle_announcements)}")
        print()
        print(f"symdiff of puzzle announcements = {sorted(eor_puzzle_announcements)}")
        print()
    print()
    print("=" * 80)
    print()
    validates = AugSchemeMPL.aggregate_verify(pks, msgs, spend_bundle.aggregated_signature)
    print(f"aggregated signature check pass: {validates}")
    print(f"pks: {pks}")
    print(f"msgs: {[msg.hex() for msg in msgs]}")
    print(f"  msg_data: {[msg.hex()[:-128] for msg in msgs]}")
    print(f"  coin_ids: {[msg.hex()[-128:-64] for msg in msgs]}")
    print(f"  add_data: {[msg.hex()[-64:] for msg in msgs]}")
    print(f"signature: {spend_bundle.aggregated_signature}")
